from functools import partial
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, TypeAdapter

import talemate.emit.async_signals as async_signals
from talemate.agents.base import AgentActionNote, AgentEmission
from talemate.decisions import (
    ActionBudget,
    PolicyAction,
    PolicyInvocation,
    decision_service,
)
from talemate.decisions.budget import fit_list, fit_text_start
from talemate.decisions.events import DecisionLog, InvocationRecord
from talemate.instance import get_agent
from talemate.util.dedupe import compile_text_to_sentences
from talemate.util.dialogue import split_passages_dialogue_and_prose
from talemate.world_state.templates.content import WritingStyle
from talemate.world_state.templates.decision_checks import DecisionCheck
from .findings import decision_findings_adapter
from .revision import RevisionInformation, _strip_character_prefix, revision_context

text_adapter = TypeAdapter(str)

ACTING_INSTRUCTIONS_CAP = 1024

async_signals.register("agent.editor.revision.decision-checks.before")


class DecisionChecksEmission(AgentEmission):
    """
    Before the decision checks of one revision run. `checks` may be changed:
    add, remove or edit checks for this message only. With no checks left,
    the usual revision runs.
    """

    info: RevisionInformation
    checks: list[DecisionCheck]
    writing_style: str


DecisionChecksUnavailableReason = Literal["no_writing_style", "no_active_checks"]


class DecisionChecksUnavailable(BaseModel):
    """Why the scene's writing style gives the decision checks nothing to run."""

    reason: DecisionChecksUnavailableReason
    writing_style: str | None = None

    @property
    def text(self) -> str:
        if self.reason == "no_writing_style":
            return "No writing style set for this scene; decision checks need one."
        return (
            f"Writing style '{self.writing_style}' has no active decision checks. "
            "Add them in its template."
        )


def active_decision_checks(writing_style: WritingStyle) -> list[DecisionCheck]:
    return [
        check
        for check in writing_style.decision_checks
        if check.active
        and (
            not check.requires_style
            or writing_style.instructions
            or writing_style.active_prose_rules
        )
    ]


def log_decision_checks_unavailable(
    log: DecisionLog, unavailable: DecisionChecksUnavailable
):
    """A Decision Log row saying why a revision ran without its checks."""
    invocation = InvocationRecord(
        id=str(uuid4()),
        template_uid="editor.decision-checks",
        outcomes=[
            {
                "action": "no_action",
                "reason": unavailable.reason,
                "details": unavailable.model_dump(
                    exclude={"reason"}, exclude_none=True
                ),
            }
        ],
    )
    log.start_invocation(invocation)
    log.finish_invocation(invocation.id, status="completed")


class DecisionChecksMixin:
    @classmethod
    def config_options(cls, agent=None):
        options = super().config_options(agent=agent)
        scene = getattr(agent, "scene", None)
        if scene is None or not scene.active:
            return options
        unavailable = agent.decision_checks_unavailable(scene)
        if unavailable:
            options["actions"]["revision"]["config"]["decision_checks"][
                "note_on_value"
            ] = {
                True: AgentActionNote(
                    text=unavailable.text, color="warning"
                ).model_dump()
            }
        return options

    @property
    def decision_checks_enabled(self):
        return self.resolve_config("revision", "decision_checks")

    @property
    def revision_decision_checks_active(self) -> bool:
        return (
            self.revision_enabled
            and self.decision_checks_enabled
            and self.revision_method in ("rewrite", "unslop")
            and not self._revision_disabled_by_context()
        )

    def decision_checks_unavailable(self, scene) -> DecisionChecksUnavailable | None:
        writing_style = scene.writing_style
        if not writing_style:
            return DecisionChecksUnavailable(reason="no_writing_style")
        if not active_decision_checks(writing_style):
            return DecisionChecksUnavailable(
                reason="no_active_checks", writing_style=writing_style.name
            )
        return None

    def decision_check_passages(
        self, info: RevisionInformation, checks: list[DecisionCheck]
    ) -> list[dict]:
        text, _ = _strip_character_prefix(info.text, info.character)
        sentences = [sentence for sentence, _ in compile_text_to_sentences(text)]
        passages = [
            {"id": f"s{index}", "text": sentence}
            for index, sentence in enumerate(sentences, 1)
        ]
        scopes = {check.scope for check in checks} - {"all"}
        if scopes and text.count('"') % 2:
            # an odd quote count flips dialogue and prose after the stray quote
            for passage in passages:
                passage["no_reliable_split"] = True
        elif scopes:
            for passage, parts in zip(
                passages, split_passages_dialogue_and_prose(text, sentences)
            ):
                passage.update(
                    {scope: getattr(parts, scope) for scope in sorted(scopes)}
                )
        return passages

    def decision_check_summaries(self, history: list[str]) -> list[str]:
        """The newest summaries, as many as the Summarizer gives its own requests."""
        keep = get_agent("summarizer").archive_include_previous
        return list(history[-keep:]) if keep else []

    def decision_check_acting_instructions(self, info: RevisionInformation) -> dict:
        """
        How the speaker talks, so a check does not flag what the acting
        instructions ask for; whole up to a fixed ceiling, never fitted to the
        decision budget.
        """
        instructions = info.character.acting_instructions if info.character else None
        instructions = fit_text_start(instructions or "", ACTING_INSTRUCTIONS_CAP)
        return {"acting_instructions": instructions} if instructions.strip() else {}

    def decision_check_state(
        self,
        info: RevisionInformation,
        checks: list[DecisionCheck],
        budget: int | None = None,
    ) -> dict[str, object]:
        scene = self.scene
        writing_style = scene.writing_style
        character_name = info.character.name if info.character else None
        # a scope part that is empty or the whole passage adds no input: the
        # policy skips it or judges the passage as All
        passages = [
            {
                key: value
                for key, value in passage.items()
                if key not in ("dialogue", "prose")
                or (value and value != passage["text"])
            }
            for passage in self.decision_check_passages(info, checks)
        ]
        state = {
            "speaker": character_name,
            **self.decision_check_acting_instructions(info),
            "passages": passages,
            "history": [],
            "writing_style": writing_style.render(scene, character_name)
            if writing_style
            else "",
            "prose_rules": [
                rule.model_dump(mode="json")
                for rule in (writing_style.active_prose_rules if writing_style else [])
            ],
            "context_type": info.context_type,
            "context_name": info.context_name,
            "source_context": info.source_context,
            "summarization_history": None,
        }
        if info.summarization_history is not None:
            return fit_list(
                state,
                "summarization_history",
                self.decision_check_summaries(info.summarization_history),
                budget,
            )
        return fit_list(
            state,
            "history",
            list(reversed(self.revision_repetition_history(with_speakers=True))),
            budget,
        )

    async def revision_with_decisions(self, info: RevisionInformation) -> str:
        def disabled_path():
            return getattr(self, f"revision_{self.revision_method}")(info)

        scene = self.scene
        unavailable = self.decision_checks_unavailable(scene)
        if unavailable and unavailable.reason == "no_writing_style":
            log_decision_checks_unavailable(decision_service.log, unavailable)
            return await disabled_path()
        writing_style = scene.writing_style
        checks = active_decision_checks(writing_style)
        emission = DecisionChecksEmission(
            agent=self,
            info=info,
            checks=[check.model_copy(deep=True) for check in checks],
            writing_style=writing_style.uid,
        )
        await async_signals.get("agent.editor.revision.decision-checks.before").send(
            emission
        )
        checks = emission.checks
        if not checks:
            # a listener may add checks to a style that has none; one that
            # removes them all leaves the style blameless
            if unavailable:
                log_decision_checks_unavailable(decision_service.log, unavailable)
            return await disabled_path()
        method = self.revision_method
        message_id = revision_context.get().message_id
        message = scene.get_message(message_id) if message_id is not None else None
        version = (
            (message.message, message.active_version, len(message.versions))
            if message
            else None
        )

        def is_current():
            return (
                self.scene is scene
                and scene.writing_style is writing_style
                and self.revision_enabled
                and self.decision_checks_enabled
                and self.revision_method == method
                and info.is_current()
                and (
                    message_id is None
                    or (
                        scene.get_message(message_id) is message
                        and message is not None
                        and (
                            message.message,
                            message.active_version,
                            len(message.versions),
                        )
                        == version
                    )
                )
            )

        revision = getattr(self, f"revision_{method}")

        async def revise(findings):
            return await revision(info=info, decision_findings=findings)

        def serialize_action_arguments(arguments):
            return {
                "text": info.text,
                "decision_findings": decision_findings_adapter.dump_python(
                    decision_findings_adapter.validate_python(arguments["findings"]),
                    mode="json",
                ),
            }

        invocation = PolicyInvocation(
            "editor.decision-checks",
            service=decision_service,
            variables={
                "info": info,
                "decision_passages": partial(
                    self.decision_check_passages, info, checks
                ),
                "decision_state": partial(self.decision_check_state, info, checks),
                "revision_method": method,
                "decision_checks": checks,
            },
            validate_result=lambda value: text_adapter.validate_python(
                value, strict=True
            ),
            disabled_path=disabled_path,
            original_result=info.text,
            can_keep=True,
            is_current=is_current,
            actions={
                "revise": PolicyAction(
                    name=f"editor.revision_{method}",
                    call=revise,
                    enabled=lambda: (
                        self.revision_decision_checks_active
                        and self.revision_method == method
                    ),
                    budget=ActionBudget(limit=1),
                    serialize_arguments=serialize_action_arguments,
                )
            },
        )
        return await invocation.run()
