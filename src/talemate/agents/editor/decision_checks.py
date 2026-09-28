from functools import partial

from pydantic import TypeAdapter

import talemate.emit.async_signals as async_signals
from talemate.agents.base import AgentEmission
from talemate.decisions import (
    ActionBudget,
    PolicyAction,
    PolicyInvocation,
    decision_service,
)
from talemate.util.dedupe import compile_text_to_sentences
from talemate.world_state.templates.decision_checks import DecisionCheck
from .findings import decision_findings_adapter
from .revision import RevisionInformation, _strip_character_prefix, revision_context

text_adapter = TypeAdapter(str)

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


class DecisionChecksMixin:
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

    def decision_check_state(self, info: RevisionInformation) -> dict[str, object]:
        scene = self.scene
        text, _ = _strip_character_prefix(info.text, info.character)
        writing_style = scene.writing_style
        character_name = info.character.name if info.character else None
        return {
            "text": info.text,
            "passages": [
                {"id": f"s{index}", "text": sentence}
                for index, (sentence, _) in enumerate(
                    compile_text_to_sentences(text), 1
                )
            ],
            "history": []
            if info.summarization_history is not None
            else list(reversed(self.revision_repetition_history())),
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
            "summarization_history": info.summarization_history,
        }

    async def revision_with_decisions(self, info: RevisionInformation) -> str:
        def disabled_path():
            return getattr(self, f"revision_{self.revision_method}")(info)

        scene = self.scene
        writing_style = scene.writing_style
        if not writing_style:
            return await disabled_path()
        checks = [
            check
            for check in writing_style.decision_checks
            if check.active
            and (
                not check.requires_style
                or writing_style.instructions
                or writing_style.active_prose_rules
            )
        ]
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

        def serialize_action_arguments(kwargs):
            findings = kwargs.get("decision_findings")
            return {
                "text": kwargs["info"].text,
                "decision_findings": decision_findings_adapter.dump_python(
                    decision_findings_adapter.validate_python(findings), mode="json"
                )
                if findings is not None
                else None,
            }

        invocation = PolicyInvocation(
            "editor.decision-checks",
            service=decision_service,
            variables={
                "info": info,
                "decision_state": partial(self.decision_check_state, info),
                "revision_method": method,
                "decision_checks": checks,
            },
            validate_result=lambda value: text_adapter.validate_python(
                value, strict=True
            ),
            disabled_path=disabled_path,
            original_result=info.text,
            is_current=is_current,
            actions={
                ("editor", f"revision_{method}"): PolicyAction(
                    call=getattr(self, f"revision_{method}"),
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
