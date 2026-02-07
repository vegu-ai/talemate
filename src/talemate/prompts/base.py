"""
Base prompt loader

The idea is to be able to specify prompts for the various agents in a way that is
changeable and extensible.
"""

import asyncio
import dataclasses
import fnmatch
import json
import traceback
import yaml
import os
import random
import re
import uuid
from contextvars import ContextVar
from datetime import datetime
from typing import Any
from enum import Enum

import jinja2
import nest_asyncio
import structlog

import talemate.instance as instance
import talemate.thematic_generators as thematic_generators
from talemate.config import get_config
from talemate.context import regeneration_context, active_scene
from talemate.emit import emit
from talemate.exceptions import LLMAccuracyError, RenderPromptError
from talemate.util import (
    count_tokens,
    limit_tokens,
    dedupe_string,
    extract_list,
    remove_extra_linebreaks,
    iso8601_diff_to_human,
)
from talemate.util.data import extract_data_auto, DataParsingError
from talemate.util.prompt import condensed, no_chapters, collapse_whitespace_lines
from talemate.agents.context import active_agent
from talemate.prompts.extensions import CaptureContextExtension
from talemate.prompts.groups import get_group_template_path, resolve_template
from talemate.prompts.response import (
    ResponseSpec,
    AsIsExtractor,
    AnchorExtractor,
    ComplexAnchorExtractor,
    CodeBlockExtractor,
    ComplexCodeBlockExtractor,
)

__all__ = [
    "Prompt",
    "register_sectioning_handler",
    "SECTIONING_HANDLERS",
    "DEFAULT_SECTIONING_HANDLER",
    "set_default_sectioning_handler",
    "active_template_uid",
]

log = structlog.get_logger("talemate")

prepended_template_dirs = ContextVar("prepended_template_dirs", default=[])
active_template_uid = ContextVar("active_template_uid", default=None)


class PydanticJsonEncoder(json.JSONEncoder):
    def default(self, obj):
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        return super().default(obj)


class StripMode(str, Enum):
    BOTH = "BOTH"
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    NONE = "NONE"


class PrependTemplateDirectories:
    def __init__(self, prepend_dir: list):
        if isinstance(prepend_dir, str):
            prepend_dir = [prepend_dir]

        self.prepend_dir = prepend_dir

    def __enter__(self):
        self.token = prepended_template_dirs.set(self.prepend_dir)

    def __exit__(self, *args):
        prepended_template_dirs.reset(self.token)


class GroupAwareLoader(jinja2.FileSystemLoader):
    """
    Custom Jinja2 loader that supports explicit template_sources overrides.

    This loader extends FileSystemLoader to check the config for explicit
    per-template source overrides before falling back to the default
    search path behavior.
    """

    def __init__(self, searchpath, agent_type: str, config):
        super().__init__(searchpath)
        self.agent_type = agent_type
        self._config = config

    def get_source(self, environment, template):
        """
        Get template source, checking for explicit source overrides first.

        For templates with explicit source overrides in config.prompts.template_sources,
        load directly from the specified group instead of using the search path.
        """
        # Check for explicit template_sources override
        prompts_config = getattr(self._config, "prompts", None)
        if prompts_config:
            template_sources = getattr(prompts_config, "template_sources", {}) or {}

            # Template name is like "name.jinja2", we need to check "agent.name"
            if template.endswith(".jinja2"):
                template_name = template[:-7]  # Remove .jinja2
            else:
                template_name = template

            uid = f"{self.agent_type}.{template_name}"

            if uid in template_sources:
                group = template_sources[uid]
                path = get_group_template_path(group, self.agent_type, template_name)
                if path.exists():
                    source = path.read_text(encoding="utf-8")
                    return source, str(path), lambda: path.stat().st_mtime

                # If explicit source not found, log warning and fall through to normal resolution
                log.warning(
                    "Explicit template source not found, using default resolution",
                    template=uid,
                    group=group,
                )

        # Fall back to normal FileSystemLoader behavior
        return super().get_source(environment, template)


nest_asyncio.apply()

SECTIONING_HANDLERS = {}
DEFAULT_SECTIONING_HANDLER = "titles"


class register_sectioning_handler:
    def __init__(self, name):
        self.name = name

    def __call__(self, func):
        SECTIONING_HANDLERS[self.name] = func
        return func


def set_default_sectioning_handler(name):
    if name not in SECTIONING_HANDLERS:
        raise ValueError(
            f"Sectioning handler {name} does not exist. Possible values are {list(SECTIONING_HANDLERS.keys())}"
        )

    global DEFAULT_SECTIONING_HANDLER
    DEFAULT_SECTIONING_HANDLER = name


def validate_line(line):
    return (
        not line.strip().startswith("//")
        and not line.strip().startswith("/*")
        and not line.strip().startswith("[end of")
    )


def clean_response(response, strip_mode: StripMode = StripMode.BOTH):
    # remove invalid lines
    cleaned = "\n".join(
        [line.rstrip() for line in response.split("\n") if validate_line(line)]
    )

    # find lines containing [end of .*] and remove the match within  the line

    cleaned = re.sub(r"\[end of .*?\]", "", cleaned, flags=re.IGNORECASE)

    if strip_mode == StripMode.BOTH:
        return cleaned.strip()
    elif strip_mode == StripMode.LEFT:
        return cleaned.lstrip()
    elif strip_mode == StripMode.RIGHT:
        return cleaned.rstrip()
    elif strip_mode == StripMode.NONE:
        return cleaned

    return cleaned.strip()


class JoinableList(list):
    def join(self, separator: str = "\n"):
        return separator.join(self)


@dataclasses.dataclass
class Prompt:
    """
    Base prompt class.
    """

    # unique prompt id {agent_type}-{prompt_name}
    uid: str

    # agent type
    agent_type: str

    # prompt name
    name: str

    # prompt text
    prompt: str = None

    # template text
    template: str | None = None

    # prompt variables
    vars: dict = dataclasses.field(default_factory=dict)

    # pad prepared response and ai response with a white-space
    pad_prepended_response: bool = True

    prepared_response: str = ""
    prepare_response_fallback: str | None = None

    # Replace json_response with data_response and data_format_type
    data_response: bool = False
    data_expected: bool = False
    data_allow_multiple: bool = False
    data_format_type: str = "json"

    client: Any = None

    sectioning_hander: str = dataclasses.field(
        default_factory=lambda: DEFAULT_SECTIONING_HANDLER
    )

    dedupe_enabled: bool = True
    strip_mode: StripMode = StripMode.BOTH
    captured_context: str = dataclasses.field(default="", init=False)

    # Extractors set by templates (can override Python-side extractors)
    _template_extractors: dict = dataclasses.field(default_factory=dict, init=False)

    # Track which source group the template was loaded from
    _source_group: str | None = dataclasses.field(default=None, repr=False)

    @classmethod
    def get(cls, uid: str, vars: dict = None):
        # split uid into agent_type and prompt_name

        try:
            agent_type, prompt_name = uid.split(".")
        except ValueError as exc:
            log.debug("prompt.get", uid=uid, error=exc)
            agent_type = ""
            prompt_name = uid

        prompt = cls(
            uid=uid,
            agent_type=agent_type,
            name=prompt_name,
            vars=vars or {},
        )

        return prompt

    @classmethod
    def from_text(cls, text: str, vars: dict = None, agent_type: str = ""):
        return cls(
            uid="",
            agent_type=agent_type,
            name="",
            template=text,
            vars=vars or {},
        )

    @classmethod
    async def request(
        cls,
        uid: str,
        client: Any,
        kind: str,
        vars: dict = None,
        response_spec: ResponseSpec | None = None,
        **kwargs,
    ):
        if "decensor" not in vars:
            vars.update(decensor=client.decensor_enabled)
        prompt = cls.get(uid, vars)

        # kwargs update prompt class attributes
        for key, value in kwargs.items():
            setattr(prompt, key, value)

        return await prompt.send(client, kind, response_spec=response_spec)

    @property
    def as_list(self):
        if not self.prompt:
            return ""
        return self.prompt.split("\n")

    @property
    def config(self):
        if not hasattr(self, "_config"):
            self._config = get_config()
        return self._config

    def __str__(self):
        return self.render()

    def template_env(self):
        # Get the directory of this file
        dir_path = os.path.dirname(os.path.realpath(__file__))

        _prepended_template_dirs = prepended_template_dirs.get() or []

        # Build template directories based on group priority
        template_dirs = list(_prepended_template_dirs)

        # Get scene from context (if available)
        scene = active_scene.get()

        # Add scene template directories (highest priority after prepended)
        scene_template_dir = getattr(scene, "template_dir", None) if scene else None
        if scene_template_dir and isinstance(scene_template_dir, str):
            # Agent-specific scene templates
            scene_agent_dir = os.path.join(scene_template_dir, self.agent_type)
            if os.path.exists(scene_agent_dir):
                template_dirs.append(scene_agent_dir)
            # Flat scene templates (backward compatibility)
            template_dirs.append(scene_template_dir)

        # Add group directories based on priority
        prompts_config = getattr(self.config, "prompts", None)
        if prompts_config:
            group_priority = getattr(prompts_config, "group_priority", []) or []
            for group in group_priority:
                if group == "user":
                    # User templates
                    user_agent_dir = os.path.join(
                        dir_path,
                        "..",
                        "..",
                        "..",
                        "templates",
                        "prompts",
                        self.agent_type,
                    )
                    if os.path.exists(user_agent_dir):
                        template_dirs.append(user_agent_dir)
                    user_common_dir = os.path.join(
                        dir_path, "..", "..", "..", "templates", "prompts", "common"
                    )
                    if os.path.exists(user_common_dir):
                        template_dirs.append(user_common_dir)
                elif group != "default":
                    # Custom group
                    custom_group_dir = os.path.join(
                        dir_path,
                        "..",
                        "..",
                        "..",
                        "templates",
                        "prompt_groups",
                        group,
                        self.agent_type,
                    )
                    if os.path.exists(custom_group_dir):
                        template_dirs.append(custom_group_dir)
                    custom_common_dir = os.path.join(
                        dir_path,
                        "..",
                        "..",
                        "..",
                        "templates",
                        "prompt_groups",
                        group,
                        "common",
                    )
                    if os.path.exists(custom_common_dir):
                        template_dirs.append(custom_common_dir)
        else:
            # Backward compatibility: if no prompts config, use user templates
            template_dirs.extend(
                [
                    os.path.join(
                        dir_path,
                        "..",
                        "..",
                        "..",
                        "templates",
                        "prompts",
                        self.agent_type,
                    ),
                    os.path.join(
                        dir_path, "..", "..", "..", "templates", "prompts", "common"
                    ),
                ]
            )

        # Always include modules directory
        template_dirs.append(
            os.path.join(dir_path, "..", "..", "..", "templates", "modules")
        )

        # Default templates (always lowest priority)
        template_dirs.extend(
            [
                os.path.join(dir_path, "templates", self.agent_type),
                os.path.join(dir_path, "templates", "common"),
            ]
        )

        # Create a jinja2 environment with the appropriate template paths
        # Use GroupAwareLoader to support explicit template_sources overrides
        return jinja2.Environment(
            loader=GroupAwareLoader(template_dirs, self.agent_type, self.config),
            extensions=[CaptureContextExtension],
        )

    def list_templates(self, search_pattern: str):
        env = self.template_env()
        found = []

        # Ensure the loader is FileSystemLoader
        if isinstance(env.loader, jinja2.FileSystemLoader):
            for search_path in env.loader.searchpath:
                for root, dirs, files in os.walk(search_path):
                    for filename in fnmatch.filter(files, search_pattern):
                        # Compute the relative path to the template directory
                        relpath = os.path.relpath(root, search_path)
                        found.append(os.path.join(relpath, filename))

        return found

    @classmethod
    def load_template_source(cls, agent_type: str, name: str) -> str:
        """
        Load the raw unrendered jinja2 template content based on agent_type and name.

        Args:
            agent_type: The agent type (empty string for scene/common templates)
            name: The template name (without .jinja2 extension)

        Returns:
            str: The raw unrendered template content

        Raises:
            jinja2.TemplateNotFound: If the template is not found
        """
        # Create a temporary Prompt instance to reuse its template_env logic
        temp_prompt = cls(
            uid="",
            agent_type=agent_type,
            name=name,
        )

        # Get template environment using Prompt's method
        env = temp_prompt.template_env()

        # Template filename should include .jinja2 extension
        template_filename = f"{name}.jinja2"

        # Get the raw template source using the loader's get_source method
        if isinstance(env.loader, jinja2.FileSystemLoader):
            template_source, template_path, _ = env.loader.get_source(
                env, template_filename
            )
            return template_source
        else:
            raise ValueError(f"Unsupported loader type for template '{name}'")

    def render(self, force: bool = False) -> str:
        """
        Render the prompt using jinja2.

        This method uses the jinja2 library to render the prompt. It first creates a jinja2 environment with the
        appropriate template paths. Then it loads the template corresponding to the prompt name. Finally, it renders
        the template with the prompt variables.

        Returns:
            str: The rendered prompt.
        """

        if self.prompt and not force:
            return self.prompt

        self.captured_context = ""
        env = self.template_env()

        ctx = {
            "bot_token": "<|BOT|>",
            "thematic_generator": thematic_generators.ThematicGenerator(),
            "regeneration_context": regeneration_context.get(),
            "active_agent": active_agent.get(),
            "agent_context_state": active_agent.get().state
            if active_agent.get()
            else {},
        }

        env.globals["render_template"] = self.render_template
        env.globals["render_and_request"] = self.render_and_request
        env.globals["prompt_instance"] = self
        env.globals["debug"] = lambda *a, **kw: log.debug(*a, **kw)
        env.globals["set_prepared_response"] = self.set_prepared_response
        env.globals["set_prepared_response_random"] = self.set_prepared_response_random
        env.globals["set_json_response"] = self.set_json_response
        env.globals["set_data_response"] = self.set_data_response
        env.globals["disable_dedupe"] = self.disable_dedupe
        env.globals["random"] = self.random
        env.globals["random_as_str"] = lambda x, y: str(random.randint(x, y))
        env.globals["random_choice"] = lambda x: random.choice(x)
        env.globals["query_scene"] = self.query_scene
        env.globals["batch_query_scene"] = self.batch_query_scene
        env.globals["query_memory"] = self.query_memory
        env.globals["query_text"] = self.query_text
        env.globals["query_text_eval"] = self.query_text_eval
        env.globals["instruct_text"] = self.instruct_text
        env.globals["agent_action"] = self.agent_action
        env.globals["agent_config"] = self.agent_config
        env.globals["rag_context_placement"] = self.rag_context_placement
        env.globals["retrieve_memories"] = self.retrieve_memories
        env.globals["time_diff"] = self.time_diff
        env.globals["system_time"] = self.system_time
        env.globals["uuidgen"] = lambda: str(uuid.uuid4())
        env.globals["to_int"] = lambda x: int(x)
        env.globals["to_str"] = lambda x: str(x)
        env.globals["config"] = self.config
        env.globals["li"] = self.get_bullet_num
        env.globals["len"] = lambda x: len(x)
        env.globals["max"] = lambda x, y: max(x, y)
        env.globals["min"] = lambda x, y: min(x, y)
        env.globals["join"] = lambda x, y: y.join(x)
        env.globals["make_list"] = lambda: JoinableList()
        env.globals["make_dict"] = lambda: {}
        env.globals["join"] = lambda x, y: y.join(x)
        env.globals["data_format_type"] = (
            lambda: getattr(self.client, "data_format", None) or self.data_format_type
        )
        env.globals["count_tokens"] = lambda x: count_tokens(
            dedupe_string(x, debug=False)
        )
        env.globals["limit_tokens"] = lambda text, limit: limit_tokens(text, limit)
        env.globals["print"] = lambda x: print(x)
        env.globals["json"] = lambda x: json.dumps(x, indent=2, cls=PydanticJsonEncoder)
        env.globals["yaml"] = lambda x: yaml.dump(x)
        env.globals["emit_status"] = self.emit_status
        env.globals["emit_system"] = lambda status, message: emit(
            "system", status=status, message=message
        )
        env.globals["llm_can_be_coerced"] = lambda: (
            self.client.can_be_coerced if self.client else False
        )
        env.globals["llm_reason_enabled"] = lambda: (
            self.client.reason_enabled if self.client else False
        )
        env.globals["text_to_chunks"] = self.text_to_chunks
        env.globals["emit_narrator"] = lambda message: emit("system", message=message)
        # Template-defined extractors
        env.globals["set_anchor_extractor"] = self.set_anchor_extractor
        env.globals["set_as_is_extractor"] = self.set_as_is_extractor
        env.globals["set_after_anchor_extractor"] = self.set_after_anchor_extractor
        env.globals["set_code_block_extractor"] = self.set_code_block_extractor
        env.filters["condensed"] = condensed
        env.filters["no_chapters"] = no_chapters
        ctx.update(self.vars)

        if "decensor" not in ctx:
            ctx["decensor"] = False

        # Load the template corresponding to the prompt name
        if not self.template:
            # no template text specified, load from file
            template = env.get_template("{}.jinja2".format(self.name))
        else:
            template = env.from_string(self.template)

        # Track source group for recently rendered templates feature
        if self.agent_type and self.name and not self.template:
            _, self._source_group = resolve_template(
                self.agent_type, self.name, active_scene.get()
            )

        sectioning_handler = SECTIONING_HANDLERS.get(self.sectioning_hander)

        try:
            self.prompt = template.render(ctx)
            if not sectioning_handler:
                log.warning(
                    "prompt.render",
                    prompt=self.name,
                    warning=f"Sectioning handler `{self.sectioning_hander}` not found",
                )
            else:
                self.prompt = sectioning_handler(self)
        except jinja2.exceptions.TemplateError as e:
            log.error("prompt.render", prompt=self.name, error=traceback.format_exc())
            emit(
                "system",
                status="error",
                message=f"Error rendering prompt `{self.name}`: {e}",
            )
            raise RenderPromptError(f"Error rendering prompt: {e}")

        self.prompt = self.render_cleanup(self.prompt)

        return self.prompt

    def render_cleanup(self, prompt_text: str):
        """
        Performs deduplication and cleanup on the rendered prompt text.
        """

        if self.dedupe_enabled:
            prompt_text = dedupe_string(prompt_text, debug=False)

        prompt_text = remove_extra_linebreaks(prompt_text)

        # find instances of `---\n+---` and compress to `---`
        prompt_text = re.sub(
            r"---\s+---", "---", prompt_text, flags=re.IGNORECASE | re.MULTILINE
        )

        # Strip exactly one trailing newline (matches previous Jinja2 render behavior)
        # TODO: remove this after investigating / fixing any impact.
        if prompt_text.endswith("\n"):
            prompt_text = prompt_text[:-1]

        # Final cleanup: remove leading whitespace-only lines and collapse
        # multiple whitespace-only lines into one
        prompt_text = collapse_whitespace_lines(prompt_text)

        return prompt_text

    def render_template(self, uid, **kwargs) -> "Prompt":
        # copy self.vars and update with kwargs
        vars = self.vars.copy()
        vars.update(kwargs)
        return Prompt.get(uid, vars=vars)

    def render_and_request(
        self, prompt: "Prompt", kind: str = "create", dedupe_enabled: bool = True
    ) -> str:
        if not self.client:
            raise ValueError("Prompt has no client set.")

        prompt.dedupe_enabled = dedupe_enabled

        loop = asyncio.get_event_loop()
        return loop.run_until_complete(prompt.send(self.client, kind=kind))

    async def loop(self, client: any, loop_name: str, kind: str = "create"):
        loop = self.vars.get(loop_name)

        while not loop.done:
            result = await self.send(client, kind=kind)
            loop.update(result)

    def get_bullet_num(self):
        _bullet_num = self.vars.get("bullet_num", 1)
        self.vars["bullet_num"] = _bullet_num + 1
        return _bullet_num

    def query_scene(
        self,
        query: str,
        at_the_end: bool = True,
        as_narrative: bool = False,
        as_question_answer: bool = True,
    ):
        from talemate.agents.editor.revision import RevisionDisabled
        from talemate.agents.summarize.analyze_scene import SceneAnalysisDisabled

        loop = asyncio.get_event_loop()
        narrator = instance.get_agent("narrator")
        query = query.format(**self.vars)

        with RevisionDisabled(), SceneAnalysisDisabled():
            if not as_question_answer:
                return loop.run_until_complete(
                    narrator.narrate_query(
                        query, at_the_end=at_the_end, as_narrative=as_narrative
                    )
                )

            return " ".join(
                [
                    f"Question: {query}",
                    "Answer: "
                    + loop.run_until_complete(
                        narrator.narrate_query(
                            query, at_the_end=at_the_end, as_narrative=as_narrative
                        )
                    ),
                ]
            )

    def batch_query_scene(
        self,
        queries: list[dict],
        max_concurrent: int = 3,
    ) -> dict[str, str]:
        """
        Execute multiple query_scene calls, potentially concurrently.

        If the narrator's client supports concurrent inference, queries will be
        executed in parallel (up to max_concurrent at a time). Otherwise, falls
        back to sequential execution.

        Args:
            queries: List of dicts with keys:
                - id: Unique identifier for the query result
                - query: The query string
                - at_the_end: Whether to focus on end of scene (default True)
                - as_narrative: Whether to return as narrative (default False)
                - as_question_answer: Whether to format as Q&A (default True)
            max_concurrent: Maximum concurrent requests (default 3)

        Returns:
            Dict mapping query id to result string
        """
        from talemate.agents.editor.revision import RevisionDisabled
        from talemate.agents.summarize.analyze_scene import SceneAnalysisDisabled

        narrator = instance.get_agent("narrator")
        client = narrator.client

        # Check if client supports concurrent inference
        supports_concurrent = getattr(client, "supports_concurrent_inference", False)

        async def execute_single_query(query_config: dict) -> tuple[str, str]:
            """Execute a single query and return (id, result)."""
            query_id = query_config["id"]
            query = query_config["query"].format(**self.vars)
            at_the_end = query_config.get("at_the_end", True)
            as_narrative = query_config.get("as_narrative", False)
            as_question_answer = query_config.get("as_question_answer", True)

            try:
                result = await narrator.narrate_query(
                    query, at_the_end=at_the_end, as_narrative=as_narrative
                )

                if as_question_answer:
                    result = f"Question: {query} Answer: {result}"

                return query_id, result
            except Exception as e:
                log.error(
                    "batch_query_scene: query failed",
                    query_id=query_id,
                    query=query[:100],
                    error=str(e),
                )
                raise RuntimeError(
                    f"Batch query failed for '{query_id}': {str(e)}"
                ) from e

        async def execute_concurrent(queries: list[dict]) -> dict[str, str]:
            """Execute queries concurrently with semaphore control.

            Raises exception if any query fails.
            """
            semaphore = asyncio.Semaphore(max_concurrent)

            async def bounded_query(query_config: dict) -> tuple[str, str]:
                async with semaphore:
                    return await execute_single_query(query_config)

            tasks = [bounded_query(q) for q in queries]
            # gather without return_exceptions will raise on first failure
            results = await asyncio.gather(*tasks)
            return dict(results)

        async def execute_sequential(queries: list[dict]) -> dict[str, str]:
            """Execute queries sequentially.

            Raises exception if any query fails.
            """
            results = {}
            for query_config in queries:
                query_id, result = await execute_single_query(query_config)
                results[query_id] = result
            return results

        loop = asyncio.get_event_loop()

        with RevisionDisabled(), SceneAnalysisDisabled():
            if supports_concurrent:
                log.debug(
                    "batch_query_scene",
                    mode="concurrent",
                    num_queries=len(queries),
                    max_concurrent=max_concurrent,
                )
                return loop.run_until_complete(execute_concurrent(queries))
            else:
                log.debug(
                    "batch_query_scene",
                    mode="sequential",
                    num_queries=len(queries),
                )
                return loop.run_until_complete(execute_sequential(queries))

    def query_text(
        self,
        query: str,
        text: str,
        as_question_answer: bool = True,
        short: bool = False,
    ):
        loop = asyncio.get_event_loop()
        world_state = instance.get_agent("world_state")
        query = query.format(**self.vars)

        if isinstance(text, list):
            text = "\n".join(text)

        if not as_question_answer:
            return loop.run_until_complete(
                world_state.analyze_text_and_answer_question(
                    text, query, response_length=10 if short else 512
                )
            )

        return "\n".join(
            [
                f"Question: {query}",
                "Answer: "
                + loop.run_until_complete(
                    world_state.analyze_text_and_answer_question(
                        text, query, response_length=10 if short else 512
                    )
                ),
            ]
        )

    def query_text_eval(self, query: str, text: str):
        query = f"{query} Answer with a yes or no."
        response = self.query_text(query, text, as_question_answer=False, short=True)
        return response.strip().lower().startswith("y")

    def query_memory(self, query: str, as_question_answer: bool = True, **kwargs):
        loop = asyncio.get_event_loop()
        memory = instance.get_agent("memory")
        query = query.format(**self.vars)

        if not kwargs.get("iterate"):
            if not as_question_answer:
                return loop.run_until_complete(memory.query(query, **kwargs))

            answer = loop.run_until_complete(memory.query(query, **kwargs))

            return "\n".join(
                [
                    f"Question: {query}",
                    f"Answer: {answer if answer else 'Unknown'}",
                ]
            )
        else:
            return loop.run_until_complete(
                memory.multi_query(
                    [q for q in query.split("\n") if q.strip()], **kwargs
                )
            )

    def instruct_text(self, instruction: str, text: str, as_list: bool = False):
        loop = asyncio.get_event_loop()
        world_state = instance.get_agent("world_state")
        instruction = instruction.format(**self.vars)

        if isinstance(text, list):
            text = "\n".join(text)

        response = loop.run_until_complete(
            world_state.analyze_and_follow_instruction(text, instruction)
        )

        if as_list:
            return extract_list(response)
        else:
            return response

    def retrieve_memories(self, lines: list[str], goal: str = None):
        loop = asyncio.get_event_loop()
        world_state = instance.get_agent("world_state")

        lines = [str(line) for line in lines]

        return loop.run_until_complete(
            world_state.analyze_text_and_extract_context("\n".join(lines), goal=goal)
        )

    def agent_config(self, config_path: str):
        try:
            agent_name, action_name, config_name = config_path.split(".")
            agent = instance.get_agent(agent_name)
            return agent.actions[action_name].config.get(config_name).value
        except Exception as e:
            log.error("agent_config", config_path=config_path, error=e)
            return ""

    def rag_context_placement(self):
        agent_ctx = active_agent.get()
        if not agent_ctx:
            return "before_history"
        return (
            self.agent_config(
                f"{agent_ctx.agent.agent_type}.use_long_term_memory.context_placement"
            )
            or "before_history"
        )

    def agent_action(self, agent_name: str, _action_name: str, **kwargs):
        loop = asyncio.get_event_loop()
        agent = instance.get_agent(agent_name)
        action = getattr(agent, _action_name)
        return loop.run_until_complete(action(**kwargs))

    def emit_status(self, status: str, message: str, **kwargs):
        if kwargs:
            emit("status", status=status, message=message, data=kwargs)
        else:
            emit("status", status=status, message=message)

    def time_diff(self, iso8601_time: str):
        scene = active_scene.get()
        if not iso8601_time:
            return ""
        return iso8601_diff_to_human(iso8601_time, scene.ts)

    def system_time(self, format: str = "full") -> str:
        """
        Returns the current system time in a clear, LLM-friendly format.

        Args:
            format: The format style to use:
                - "full": "Thursday, February 5, 2026 at 2:30 PM" (default)
                - "date": "February 5, 2026"
                - "time": "2:30 PM"
                - "iso": "2026-02-05T14:30:45"
                - "datetime": "2026-02-05 14:30:45"

        Returns:
            str: The formatted current time string.
        """
        now = datetime.now()

        if format == "full":
            return now.strftime("%A, %B %-d, %Y at %-I:%M %p")
        elif format == "date":
            return now.strftime("%B %-d, %Y")
        elif format == "time":
            return now.strftime("%-I:%M %p")
        elif format == "iso":
            return now.strftime("%Y-%m-%dT%H:%M:%S")
        elif format == "datetime":
            return now.strftime("%Y-%m-%d %H:%M:%S")
        else:
            return now.strftime("%A, %B %-d, %Y at %-I:%M %p")

    def text_to_chunks(self, text: str, chunk_size: int = 512) -> list[str]:
        """
        Takes a text string and splits it into chunks based length of the text.

        Arguments:

        - text: The text to split into chunks.
        - chunk_size: number of characters in each chunk.
        """

        chunks = []

        for i, line in enumerate(text.split("\n")):
            # dont push empty lines into empty chunks
            if not line.strip() and (not chunks or not chunks[-1]):
                continue

            if not chunks:
                chunks.append([line])
                continue

            if len("\n".join(chunks[-1])) + len(line) < chunk_size:
                chunks[-1].append(line)
            else:
                chunks.append([line])

        return ["\n\n".join(chunk) for chunk in chunks]

    def set_prepared_response(
        self, response: str, prepend: str = "", fallback: str | None = None
    ):
        """
        Set the prepared response.

        Args:
            response (str): The prepared response.
        """
        self.prepared_response = response
        self.prepare_response_fallback = fallback or response
        return f"<|BOT|>{prepend}{response}"

    def set_prepared_response_random(self, responses: list[str], prefix: str = ""):
        """
        Set the prepared response from a list of responses using random.choice

        Args:

            responses (list[str]): A list of responses.
        """

        response = random.choice(responses)
        return self.set_prepared_response(f"{prefix}{response}")

    def set_data_response(
        self, initial_object: dict, instruction: str = "", cutoff: int = 3
    ):
        """
        Prepares for a data response in the client's preferred format (YAML or JSON)

        Args:
            initial_object (dict): The data structure to serialize
            instruction (str): Optional instruction/schema comment
            cutoff (int): Number of lines to trim from the end
        """
        # Always use client data format if available
        data_format_type = (
            getattr(self.client, "data_format", None) or self.data_format_type
        )

        self.data_format_type = data_format_type
        self.data_response = True

        if data_format_type == "yaml":
            if yaml is None:
                raise ImportError(
                    "PyYAML is required for YAML support. Please install it with 'pip install pyyaml'."
                )

            # Serialize to YAML
            prepared_response = yaml.safe_dump(initial_object, sort_keys=False).split(
                "\n"
            )

            # For list structures, ensure we stop after the key with a colon
            if isinstance(initial_object, dict) and any(
                isinstance(v, list) for v in initial_object.values()
            ):
                # Find the first key that has a list value and stop there
                for i, line in enumerate(prepared_response):
                    if line.strip().endswith(":"):  # Found a key that might have a list
                        # Look ahead to see if next line has a dash (indicating it's a list)
                        if i + 1 < len(prepared_response) and prepared_response[
                            i + 1
                        ].strip().startswith("- "):
                            # Keep only up to the key with colon, drop the list items
                            prepared_response = prepared_response[: i + 1]
                            break
            # For nested dictionary structures, keep only the top-level keys
            elif isinstance(initial_object, dict) and any(
                isinstance(v, dict) for v in initial_object.values()
            ):
                # Find keys that have dictionary values
                for i, line in enumerate(prepared_response):
                    if line.strip().endswith(
                        ":"
                    ):  # Found a key that might have a nested dict
                        # Look ahead to see if next line is indented (indicating nested structure)
                        if i + 1 < len(prepared_response) and prepared_response[
                            i + 1
                        ].startswith("  "):
                            # Keep only up to the key with colon, drop the nested content
                            prepared_response = prepared_response[: i + 1]
                            break
            elif cutoff > 0:
                # For other structures, just remove last lines
                prepared_response = prepared_response[:-cutoff]

            if instruction:
                prepared_response.insert(0, f"# {instruction}")

            cleaned = "\n".join(prepared_response)
            # Wrap in markdown code block for YAML, but do not close the code block
            # Add an extra newline to ensure the model's response starts on a new line
            return self.set_prepared_response(f"```yaml\n{cleaned}")
        else:
            # Use existing JSON logic
            prepared_response = json.dumps(initial_object, indent=2).split("\n")
            prepared_response = ["".join(prepared_response[:-cutoff])]
            if instruction:
                prepared_response.insert(0, f"// {instruction}")
            cleaned = "\n".join(prepared_response)
            # remove all duplicate whitespace
            cleaned = re.sub(r"\s+", " ", cleaned)
            return self.set_prepared_response(f"```json\n{cleaned}")

    def set_json_response(
        self, initial_object: dict, instruction: str = "", cutoff: int = 3
    ):
        """
        Prepares for a json response
        """
        self.data_format_type = "json"
        return self.set_data_response(
            initial_object, instruction=instruction, cutoff=cutoff
        )

    def disable_dedupe(self):
        self.dedupe_enabled = False
        return ""

    # =========================================================================
    # Template-defined extractor methods
    # These functions are available in Jinja2 templates to define custom
    # extractors that override Python-side defaults.
    # =========================================================================

    def set_anchor_extractor(
        self,
        name: str,
        left: str,
        right: str,
        trim: bool = True,
        fallback_to_full: bool = False,
        tracked_tags: list[str] | None = None,
    ) -> str:
        """
        Register an anchor extractor that overrides Python default.

        Can be called from Jinja2 templates:
            {{ set_anchor_extractor("message", "<RESPONSE>", "</RESPONSE>") }}

        For nesting awareness, use tracked_tags:
            {{ set_anchor_extractor("message", "<MESSAGE>", "</MESSAGE>", tracked_tags=["ANALYSIS", "MESSAGE", "ACTIONS"]) }}

        Args:
            name: The field name this extractor is for
            left: Left anchor (e.g., "<MESSAGE>")
            right: Right anchor (e.g., "</MESSAGE>")
            trim: Whether to trim whitespace from extracted content
            fallback_to_full: If True, return full response when anchors not found
            tracked_tags: List of tag names to track for nesting awareness.
                If provided, uses ComplexAnchorExtractor for nesting-aware extraction.

        Returns:
            Empty string (no output in template)
        """
        if tracked_tags:
            self._template_extractors[name] = ComplexAnchorExtractor(
                left=left,
                right=right,
                trim=trim,
                fallback_to_full=fallback_to_full,
                tracked_tags=tracked_tags,
            )
        else:
            self._template_extractors[name] = AnchorExtractor(
                left=left,
                right=right,
                trim=trim,
                fallback_to_full=fallback_to_full,
            )
        return ""

    def set_as_is_extractor(self, name: str, trim: bool = True) -> str:
        """
        Register an as-is extractor that returns the full response.

        Can be called from Jinja2 templates:
            {{ set_as_is_extractor("narration") }}

        Args:
            name: The field name this extractor is for
            trim: Whether to trim whitespace from extracted content

        Returns:
            Empty string (no output in template)
        """
        from talemate.prompts.response import AsIsExtractor

        self._template_extractors[name] = AsIsExtractor(trim=trim)
        return ""

    def set_after_anchor_extractor(
        self,
        name: str,
        start: str,
        stop_at: str | None = None,
        trim: bool = True,
        fallback_to_full: bool = False,
    ) -> str:
        """
        Register an after-anchor extractor.

        Can be called from Jinja2 templates:
            {{ set_after_anchor_extractor("summary", "SUMMARY:") }}

        Args:
            name: The field name this extractor is for
            start: The start marker to search for
            stop_at: Optional end marker to stop at
            trim: Whether to trim whitespace from extracted content
            fallback_to_full: If True, return full response when start marker not found

        Returns:
            Empty string (no output in template)
        """
        from talemate.prompts.response import AfterAnchorExtractor

        self._template_extractors[name] = AfterAnchorExtractor(
            start=start,
            stop_at=stop_at,
            trim=trim,
            fallback_to_full=fallback_to_full,
        )
        return ""

    def set_code_block_extractor(
        self,
        name: str,
        left: str,
        right: str,
        validate_structured: bool = True,
        trim: bool = True,
        tracked_tags: list[str] | None = None,
    ) -> str:
        """
        Register a code block extractor for JSON/YAML content.

        Can be called from Jinja2 templates:
            {{ set_code_block_extractor("actions", "<ACTIONS>", "</ACTIONS>") }}

        For nesting awareness, use tracked_tags:
            {{ set_code_block_extractor("actions", "<ACTIONS>", "</ACTIONS>", tracked_tags=["ANALYSIS", "MESSAGE", "ACTIONS"]) }}

        Args:
            name: The field name this extractor is for
            left: Left anchor (e.g., "<ACTIONS>")
            right: Right anchor (e.g., "</ACTIONS>")
            validate_structured: Whether to validate content as JSON/YAML
            trim: Whether to trim whitespace from extracted content
            tracked_tags: List of tag names to track for nesting awareness.
                If provided, uses ComplexCodeBlockExtractor for nesting-aware extraction.

        Returns:
            Empty string (no output in template)
        """
        if tracked_tags:
            self._template_extractors[name] = ComplexCodeBlockExtractor(
                left=left,
                right=right,
                validate_structured=validate_structured,
                trim=trim,
                tracked_tags=tracked_tags,
            )
        else:
            self._template_extractors[name] = CodeBlockExtractor(
                left=left,
                right=right,
                validate_structured=validate_structured,
                trim=trim,
            )
        return ""

    def random(self, min: int, max: int):
        return random.randint(min, max)

    async def parse_data_response(self, response: str) -> dict | list[dict]:
        """
        Parse response based on configured data format
        """
        data_format_type = (
            getattr(self.client, "data_format", None) or self.data_format_type
        )
        try:
            structures = await extract_data_auto(
                response, self.client, self, data_format_type
            )
        except DataParsingError as exc:
            raise LLMAccuracyError(
                f"{self.name} - Error parsing data response: {exc}",
                model_name=self.client.model_name if self.client else "unknown",
            )

        log.debug("parse_data_response", structures=structures)

        if self.data_allow_multiple:
            return structures
        else:
            try:
                return structures[0]
            except IndexError:
                return {}

    async def send(
        self,
        client: Any,
        kind: str = "create",
        response_spec: ResponseSpec | None = None,
        dedupe_enabled: bool | None = None,  # None = use client/config default
    ) -> tuple[str, dict[str, str | list[str] | None]]:
        """
        Send the prompt to the client.

        Args:
            client (Any): The client to send the prompt to.
            kind (str): The kind of prompt to send.
            response_spec (ResponseSpec | None): Response spec for extraction. If not provided,
                defaults to AsIsExtractor for "response" field.
            dedupe_enabled (bool | None): Whether to enable deduplication (currently unused,
                reserved for future implementation).

        Returns:
            tuple[str, dict]: The response and extracted fields. If data_response=True,
                returns (response, parsed_data). Otherwise returns (response, extracted_dict)
                where extracted_dict contains fields defined in response_spec.
        """

        self.client = client

        # Set the active template_uid context for tracking
        token = active_template_uid.set(self.uid if self.uid else None)
        try:
            response = await client.send_prompt(
                str(self),
                kind=kind,
                data_expected=self.data_response or self.data_expected,
            )
        finally:
            active_template_uid.reset(token)

        # Handle prepared response prepending based on response format
        if not self.data_response:
            lookfor = self.prepare_response_fallback or self.prepared_response

            # not awaiting a structured response
            if not response.lstrip().lower().startswith(lookfor.lower()):
                pad = " " if self.pad_prepended_response else ""
                response = self.prepared_response.rstrip() + pad + response.strip()
        else:
            format_type = (
                getattr(self.client, "data_format", None) or self.data_format_type
            )

            json_start = response.lstrip().startswith(self.prepared_response.lstrip())
            yaml_block = "```yaml" in response
            json_block = "```json" in response

            if format_type == "json" and json_block:
                response = response.split("```json", 1)[1].split("```", 1)[0]
            elif format_type == "yaml" and yaml_block:
                response = response.split("```yaml", 1)[1].split("```", 1)[0].strip()
            else:
                # If response doesn't start with expected format markers, prepend the prepared response
                if (format_type == "json" and not json_start) or (
                    format_type == "yaml" and not yaml_block
                ):
                    pad = " " if self.pad_prepended_response else ""
                    if format_type == "yaml":
                        if self.client.can_be_coerced:
                            response = self.prepared_response + response.rstrip()
                        else:
                            response = (
                                self.prepared_response.rstrip()
                                + "\n  "
                                + response.rstrip()
                            )
                    else:
                        response = (
                            self.prepared_response.rstrip() + pad + response.strip()
                        )

        if self.data_response:
            log.debug(
                "data_response",
                format_type=self.data_format_type,
                response=response,
                prepared_response=self.prepared_response,
            )
            # Emit template_rendered signal for tracking
            if self.uid and self._source_group:
                emit(
                    "template_rendered",
                    data={"uid": self.uid, "source_group": self._source_group},
                )
            return response, await self.parse_data_response(response)

        response = clean_response(response, strip_mode=self.strip_mode)

        # Default to AsIsExtractor for "response" field if no response_spec provided
        if response_spec is None:
            response_spec = ResponseSpec.simple(
                "response", AsIsExtractor(), required=False
            )

        # Merge: Python defaults + template overrides (template wins)
        merged_extractors = {**response_spec.extractors}
        template_extractors = getattr(self, "_template_extractors", {})
        if template_extractors:
            merged_extractors.update(template_extractors)  # Template overrides Python

        # Build effective spec with merged extractors
        effective_spec = ResponseSpec(
            extractors=merged_extractors, required=response_spec.required
        )

        extracted = effective_spec.extract_all(response)

        # Emit template_rendered signal for tracking
        if self.uid and self._source_group:
            emit(
                "template_rendered",
                data={"uid": self.uid, "source_group": self._source_group},
            )

        return response, extracted

    def poplines(self, num):
        """
        Pop the first n lines from the prompt.

        Args:
            num (int): The number of lines to pop.
        """
        lines = self.as_list[:-num]
        self.prompt = "\n".join(lines)

    def cleaned(self, as_list: bool = False):
        """
        Clean the prompt.
        """
        cleaned = []

        for line in self.as_list:
            if "<|BOT|>" in line:
                cleaned.append(line.split("<|BOT|>")[0])
                break
            cleaned.append(line)

        if as_list:
            return cleaned
        return "\n".join(cleaned)


def _prompt_sectioning(
    prompt: Prompt,
    handle_open: callable,
    handle_close: callable,
    strip_empty_lines: bool = False,
) -> str:
    """
    Will loop through the prompt lines and find <|SECTION:{NAME}|> and <|CLOSE_SECTION|> tags
    and replace them with section tags according to the handle_open and handle_close functions.

    Arguments:
        prompt (Prompt): The prompt to section.
        handle_open (callable): A function that takes the section name as an argument and returns the opening tag.
        handle_close (callable): A function that takes the section name as an argument and returns the closing tag.
        strip_empty_lines (bool): Whether to strip empty lines after opening and before closing tags.
    """

    # loop through the prompt lines and find <|SECTION:{NAME}|> tags
    # keep track of currently open sections and close them when a new one is found
    #
    # sections are either closed by a <|CLOSE_SECTION|> tag or a new <|SECTION:{NAME}|> tag

    lines = prompt.as_list

    section_name = None

    new_lines = []
    at_beginning_of_section = False

    def _handle_strip_empty_lines_on_close():
        if not strip_empty_lines:
            return
        while new_lines[-1] == "":
            new_lines.pop()

    for line in lines:
        if "<|SECTION:" in line:
            if not handle_open:
                continue

            if section_name and handle_close:
                if at_beginning_of_section:
                    new_lines.pop()
                else:
                    _handle_strip_empty_lines_on_close()
                    new_lines.append(handle_close(section_name))
                    new_lines.append("")

            section_name = line.split("<|SECTION:")[1].split("|>")[0].lower()
            new_lines.append(handle_open(section_name))
            at_beginning_of_section = True
            continue

        if "<|CLOSE_SECTION|>" in line and section_name:
            if at_beginning_of_section:
                section_name = None
                new_lines.pop()
                continue

            if not handle_close:
                section_name = None
                continue
            _handle_strip_empty_lines_on_close()
            new_lines.append(handle_close(section_name))
            section_name = None
            continue
        elif "<|CLOSE_SECTION|>" in line and not section_name:
            continue

        if line == "" and strip_empty_lines and at_beginning_of_section:
            continue

        at_beginning_of_section = False

        new_lines.append(line)

    return "\n".join(new_lines)


@register_sectioning_handler("bracket")
def bracket_prompt_sectioning(prompt: Prompt) -> str:
    """
    Will loop through the prompt lines and find <|SECTION:{NAME}|> and <|CLOSE_SECTION|> tags
    and replace them with a bracketed section.

    Bracketed sections have both a beginning and end tag.
    """

    return _prompt_sectioning(
        prompt,
        lambda section_name: f"[{section_name}]",
        lambda section_name: f"[end of {section_name}]",
        strip_empty_lines=True,
    )


@register_sectioning_handler("none")
def none_prompt_sectioning(prompt: Prompt) -> str:
    return _prompt_sectioning(
        prompt,
        None,
        None,
    )


@register_sectioning_handler("titles")
def titles_prompt_sectioning(prompt: Prompt) -> str:
    return _prompt_sectioning(
        prompt,
        lambda section_name: f"\n## {section_name.capitalize()}",
        None,
    )


@register_sectioning_handler("html")
def html_prompt_sectioning(prompt: Prompt) -> str:
    return _prompt_sectioning(
        prompt,
        lambda section_name: f"<{section_name.capitalize().replace(' ', '')}>",
        lambda section_name: f"</{section_name.capitalize().replace(' ', '')}>",
        strip_empty_lines=True,
    )
