"""
FOCAL (Function Orchestration and Creative Argument Layer) separates structured function execution from creative text generation in AI prompts. It first generates function calls with placeholders, then fills these with creative content in a separate phase, and finally combines them into python function calls.

Talemate uses these for tasks where a structured function call is needed with creative content, such as in the case of generating a story, characters or dialogue.

This does NOT use API specific function calling (like openai or anthropic), but rather builds its own set of instructions, so opensource and private APIs can be used interchangeably (in theory).
"""

import structlog
import traceback
from typing import Callable, TYPE_CHECKING
from contextvars import ContextVar

from talemate.client.base import ClientBase
from talemate.prompts.base import Prompt
from talemate.util.data import (
    extract_data,
)
from talemate.instance import get_agent

from .schema import Argument, Call, Callback, State


if TYPE_CHECKING:
    from talemate.agents.director import DirectorAgent

__all__ = [
    "Argument",
    "Call",
    "Callback",
    "Focal",
    "FocalContext",
    "collect_calls",
    "current_focal_context",
]

log = structlog.get_logger("talemate.game.focal")

current_focal_context = ContextVar("current_focal_context", default=None)


class FocalContext:
    def __init__(self):
        self.hooks_before_call = []
        self.hooks_after_call = []
        self.value = {}

    def __enter__(self):
        self.token = current_focal_context.set(self)
        return self

    def __exit__(self, *args):
        current_focal_context.reset(self.token)

    async def process_before_hooks(self, call: Call):
        for hook in self.hooks_before_call:
            await hook(call)

    async def process_after_hooks(self, call: Call):
        for hook in self.hooks_after_call:
            await hook(call)


class Focal:
    schema_formats: list[str] = ["json", "yaml"]

    def __init__(
        self,
        client: ClientBase,
        callbacks: list[Callback],
        max_calls: int = 5,
        retries: int = 0,
        schema_format: str = "json",
        response_length: int = 1024,
        **kwargs,
    ):
        self.client = client
        self.context = kwargs
        self.max_calls = max_calls
        self.retries = retries
        self.response_length = response_length
        self.state = State(schema_format=schema_format)
        self.callbacks = {callback.name: callback for callback in callbacks}

        # set state on each callback
        for callback in self.callbacks.values():
            callback.state = self.state

    def render_instructions(self) -> str:
        prompt = Prompt.get(
            "focal.instructions",
            {
                "max_calls": self.max_calls,
                "state": self.state,
            },
        )
        return prompt.render()

    async def request(
        self,
        template_name: str | None = None,
        prompt: Prompt | None = None,
        retry_state: dict | None = None,
    ) -> str:
        log.debug(
            "focal.request", template_name=template_name, callbacks=self.callbacks
        )

        # client preference for schema format
        if self.client.data_format:
            self.state.schema_format = self.client.data_format

        if template_name:
            # Render new prompt instance from template name
            response = await Prompt.request(
                template_name,
                self.client,
                f"analyze_{self.response_length}",
                vars={
                    **self.context,
                    "focal": self,
                    "max_tokens": self.client.max_token_length,
                    "max_calls": self.max_calls,
                },
                dedupe_enabled=False,
            )
        elif prompt:
            # Prepared prompt instance was submitted
            prompt.vars.update(
                {
                    "focal": self,
                    "max_tokens": self.client.max_token_length,
                    "max_calls": self.max_calls,
                    "decensor": self.client.decensor_enabled,
                }
            )
            prompt.dedupe_enabled = False
            prompt.render(force=True)
            response = await prompt.send(self.client, f"analyze_{self.response_length}")
        else:
            raise ValueError("Must provide either template_name or prompt")

        response = response.strip()

        if not retry_state:
            retry_state = {"retries": self.retries}

        if not response:
            log.warning("focal.request.empty_response")

        log.debug("focal.request", template_name=template_name, response=response)

        if response:
            await self._execute(response, State())

        # if no calls were made and we still have retries, try again
        if not self.state.calls and retry_state["retries"] > 0:
            log.warning(
                "focal.request - NO CALLS MADE - retrying",
                retries=retry_state["retries"],
            )
            retry_state["retries"] -= 1
            return await self.request(template_name, retry_state)

        return response

    async def _execute(self, response: str, state: State):
        try:
            calls: list[Call] = await self._extract(response)
        except Exception as e:
            log.error("focal.extract_error", error=str(e))
            return

        focal_context = current_focal_context.get()

        calls_made = 0

        director: "DirectorAgent" = get_agent("director")

        for call in calls:
            if calls_made >= self.max_calls:
                log.warning("focal.execute.max_calls_reached", max_calls=self.max_calls)
                break

            if call.name not in self.callbacks:
                log.warning("focal.execute.unknown_callback", name=call.name)
                continue

            callback = self.callbacks[call.name]

            try:
                # if we have a focal context, process additional hooks (before call)
                if focal_context:
                    await focal_context.process_before_hooks(call)

                log.debug(
                    f"focal.execute - Calling {callback.name}", arguments=call.arguments
                )

                await director.log_function_call(call)

                result = await callback.fn(**call.arguments)
                call.result = result
                call.called = True
                calls_made += 1

                # if we have a focal context, process additional hooks (after call)
                if focal_context:
                    await focal_context.process_after_hooks(call)

            except Exception as e:
                if getattr(e, "focal_reraise", False):
                    raise e
                log.error(
                    "focal.execute.callback_error",
                    callback=call.name,
                    error=traceback.format_exc(),
                )
                call.error = str(e)

            self.state.calls.append(call)

    async def _extract(self, response: str) -> list[Call]:
        # first try to extract data from the response using tooling
        try:
            data = extract_data(response, self.state.schema_format)
            return [Call(**call) for call in data]
        except Exception as e:
            log.warning(
                "focal.extract.data FAILED - attempting to use AI to extract calls",
                error=str(e),
            )

        # if there is no JSON structure in the response, there are no calls to extract
        # so we return an empty list
        if f"```{self.state.schema_format}" not in response:
            log.warning("focal.extract.no_json_structure")
            return []

        log.debug("focal.extract", response=response)

        _, calls_json = await Prompt.request(
            "focal.extract_calls",
            self.client,
            f"analyze_{self.response_length}",
            vars={
                **self.context,
                "text": response,
                "focal": self,
                "max_tokens": self.client.max_token_length,
            },
            dedupe_enabled=False,
        )

        calls = [Call(**call) for call in calls_json.get("calls", [])]

        log.debug("focal.extract", calls=calls)

        return calls


def collect_calls(
    calls: list[Call], nested: bool = False, filter: Callable = None
) -> list:
    """
    Takes a list of calls and collects into a list.

    If nested is True and call result is a list of calls, it will also collect those.

    If a filter function is provided, it will be used to filter the results.
    """

    results = []

    for call in calls:
        result_is_list_of_calls = isinstance(call.result, list) and all(
            [isinstance(result, Call) for result in call.result]
        )

        # we need to filter the results
        # but if nested is True, we need to collect nested results regardless

        if not filter or filter(call):
            results.append(call)

        if nested and result_is_list_of_calls:
            results.extend(collect_calls(call.result, nested=True, filter=filter))

    return results
