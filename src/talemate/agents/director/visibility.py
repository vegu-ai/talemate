"""On-demand authored visibility assessment; proposals are not learning events."""

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Literal

import pydantic
import structlog

from talemate.agents.base import set_processing
from talemate.client.presets import make_kind
from talemate.exceptions import GenerationCancelled
from talemate.game.engine.context_id import (
    CharacterContext,
    WorldEntryContext,
    WorldEntryContextItem,
    context_id_item_by_name,
    context_id_item_from_string,
)
from talemate.knowledge.entry import EntryKnowledge, resolve_character_names
from talemate.knowledge.schema import (
    EntryVisibility,
    VisibilityMode,
    is_memory_attribute,
)
from talemate.prompts import Prompt
from talemate.prompts.base import SECTION_FORMAT_TO_HANDLER
from talemate.util import count_tokens
from talemate.util.data import extract_json, fix_faulty_json

log = structlog.get_logger("talemate.agents.director.visibility")
MAX_ASSESSMENT_ENTRIES = 32
MAX_ASSESSMENT_TOKENS = 16384
MAX_RESPONSE_TOKENS = 4096
MAX_HISTORY_TOKENS = 2048


class VisibilityAssessmentError(ValueError):
    """A user-correctable assessment failure."""


class StaleVisibilityAssessment(GenerationCancelled):
    """The proposed batch no longer matches the selected entries."""


class VisibilitySelection(pydantic.BaseModel):
    scope: Literal["attributes", "details", "world_entries"]
    character: str | None = None
    world_entries: list[str] = pydantic.Field(default_factory=list)
    instructions: str = pydantic.Field(min_length=1, max_length=8000)
    reassess: pydantic.StrictBool = False

    @pydantic.field_validator("reassess", mode="before")
    @classmethod
    def canonical_reassess(cls, value):
        if value is None:
            return False
        if isinstance(value, str):
            canonical = value.strip().lower()
            if canonical in ("true", "yes", "1"):
                return True
            if canonical in ("false", "no", "0"):
                return False
        return value


class ProposedVisibility(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid", strict=True)

    mode: VisibilityMode
    characters: list[str] = pydantic.Field(default_factory=list)


class VisibilityDecision(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid", strict=True)

    context_id: str
    outcome: Literal["set", "mixed", "uncertain"]
    reason: str = pydantic.Field(min_length=1, max_length=2000)
    visibility: ProposedVisibility | None = None


@dataclass
class AssessedEntry:
    context_id: str
    owner: str | None
    key: str
    kind: Literal["attributes", "details", "world_entries"]
    text: str
    visibility: EntryVisibility
    subject: Any = field(repr=False)

    @property
    def name(self) -> str:
        return self.key.removeprefix("detail.") if self.kind == "details" else self.key

    @property
    def label(self) -> str:
        return (
            f"{self.owner}: {self.name}" if self.owner else f"World entry: {self.name}"
        )

    def known_by(self, visibility: EntryVisibility) -> str:
        return EntryKnowledge(
            id=self.context_id,
            kind="world_entry" if self.kind == "world_entries" else "attribute",
            owner=self.owner,
            visibility=visibility,
        ).known_by

    def current(self, scene) -> bool:
        if self.kind == "world_entries":
            subject = scene.world_state.manual_context_for_world().get(self.key)
            return (
                subject is self.subject
                and subject.text == self.text
                and subject.visibility == self.visibility
            )
        subject = scene.character_data.get(self.owner)
        if subject is not self.subject:
            return False
        values = (
            subject.base_attributes if self.kind == "attributes" else subject.details
        )
        return (
            self.name in values
            and str(values[self.name]) == self.text
            and subject.visibility.get(self.key, EntryVisibility()) == self.visibility
        )

    def payload(self) -> dict:
        return {
            "context_id": self.context_id,
            "name": self.name,
            "owner": self.owner,
            "text": self.text,
            "visibility": self.visibility.model_dump(),
        }


@dataclass
class VisibilityAssessment:
    scene: Any = field(repr=False)
    context: dict
    entries: list[AssessedEntry]
    proposals: list[tuple[AssessedEntry, EntryVisibility, str]] = field(
        default_factory=list
    )
    feedback: list[str] = field(default_factory=list)
    invalid_decisions: int = 0
    consumed: bool = False

    def require_current(self, scene):
        if (
            self.consumed
            or scene is not self.scene
            or set(scene.character_data) != set(self.context["cast"])
            or any(not entry.current(scene) for entry in self.entries)
        ):
            raise StaleVisibilityAssessment(
                "Visibility assessment is stale; request a fresh assessment. No changes applied."
            )

    def report(self, applied=False) -> str:
        lines = ["Best-effort visibility assessment."]
        for entry, visibility, reason in self.proposals:
            lines.append(
                f"{'Updated' if applied else 'Proposed'} {entry.label} (`{entry.context_id}`): "
                f"{entry.known_by(entry.visibility)} → {entry.known_by(visibility)}. {reason}"
            )
        lines.extend(self.feedback)
        if self.invalid_decisions:
            lines.append(
                f"{self.invalid_decisions} decision(s) failed validation; review the diagnostics above."
            )
        if not self.proposals:
            lines.append("No visibility changes proposed.")
        lines.append(
            "Existing disclosures and grants remain; this does not make characters forget."
        )
        return "\n".join(lines)


def assessment_context(scene, history_budget=MAX_HISTORY_TOKENS) -> dict:
    return {
        "description": scene.description,
        "story_intent": scene.story_intent,
        "scene_intent": scene.intent_state.phase.intent
        if scene.intent_state.phase
        else None,
        "cast": list(scene.character_data),
        "time": scene.ts,
        "history": scene.context_history(budget=history_budget),
    }


async def select_visibility_entries(
    scene, selection: VisibilitySelection
) -> list[AssessedEntry]:
    entries = []
    if selection.scope in ("attributes", "details"):
        if selection.world_entries:
            raise VisibilityAssessmentError(
                "world_entries: cannot be combined with a character scope."
            )
        character = scene.get_character(selection.character or "")
        if character is None:
            raise VisibilityAssessmentError(
                "character: choose an existing character for attributes or details."
            )
        context = CharacterContext(character=character)
        items = (
            context.attributes if selection.scope == "attributes" else context.details
        )
        for item in items:
            if selection.scope == "attributes" and not is_memory_attribute(item.name):
                continue
            key = (
                item.name if selection.scope == "attributes" else f"detail.{item.name}"
            )
            entries.append(
                AssessedEntry(
                    context_id=str(item.context_id),
                    owner=character.name,
                    key=key,
                    kind=selection.scope,
                    text=str(item.value),
                    subject=character,
                    visibility=character.visibility.get(
                        key, EntryVisibility()
                    ).model_copy(deep=True),
                )
            )
    else:
        if selection.character:
            raise VisibilityAssessmentError(
                "character: a world-entry scope cannot include a character selector."
            )
        if not selection.world_entries:
            raise VisibilityAssessmentError(
                "world_entries: select specific entries; an empty list does not mean all."
            )
        items = list(WorldEntryContext()._items(scene))
        pending = list(selection.world_entries)
        while pending:
            value = pending.pop(0)
            item = context_id_item_by_name(items, value)
            if item is None:
                value = value.strip().strip("`")
                item = context_id_item_by_name(items, value)
            if item is None and ":" in value:
                try:
                    item = await context_id_item_from_string(value.strip(), scene)
                except ValueError as exc:
                    if "," not in value:
                        raise VisibilityAssessmentError(
                            f"world_entries: `{value}` is not an existing world entry."
                        ) from exc
            if item is None and "," in value:
                pending[0:0] = [part for part in value.split(",") if part.strip()]
                continue
            if not isinstance(item, WorldEntryContextItem):
                raise VisibilityAssessmentError(
                    f"world_entries: `{value}` is not an existing world entry."
                )
            subject = item.entry
            if any(entry.key == subject.id for entry in entries):
                continue
            entries.append(
                AssessedEntry(
                    context_id=str(item.context_id),
                    owner=None,
                    key=subject.id,
                    kind="world_entries",
                    text=subject.text,
                    subject=subject,
                    visibility=subject.visibility.model_copy(deep=True),
                )
            )
    return entries


def collect_visibility_decisions(
    plan: VisibilityAssessment, eligible: list[AssessedEntry], data
):
    if not isinstance(data, dict) or not isinstance(data.get("decisions"), list):
        raise VisibilityAssessmentError(
            "Assessment returned no decision list; nothing was changed."
        )
    rows = data["decisions"]
    counts = Counter()
    by_id = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("context_id"), str):
            identity = row["context_id"].strip().strip("`").strip()
            counts[identity] += 1
            by_id[identity] = row
    if set(by_id) - {entry.context_id for entry in eligible}:
        plan.feedback.append(
            "Ignored decisions for entries outside the assessment scope."
        )

    def invalid(entry, reason):
        plan.invalid_decisions += 1
        plan.feedback.append(
            f"Unchanged {entry.label}: {reason}; assess again or set Known by manually."
        )
        log.warning(
            "visibility_decision_invalid", context_id=entry.context_id, reason=reason
        )

    for entry in eligible:
        if counts[entry.context_id] != 1:
            invalid(entry, "missing or duplicate decision")
            continue
        try:
            decision = VisibilityDecision.model_validate(by_id[entry.context_id])
        except pydantic.ValidationError as exc:
            diagnostics = "; ".join(
                f"{'.'.join(map(str, error['loc']))}: {error['msg']}"
                for error in exc.errors(include_input=False)
            )
            invalid(entry, diagnostics)
            continue
        if decision.outcome != "set":
            correction = (
                "Split public and private content into separate entries, then set Known by."
                if decision.outcome == "mixed"
                else "Review the evidence and set Known by manually."
            )
            plan.feedback.append(
                f"Unchanged {entry.label} ({decision.outcome}): {decision.reason} {correction}"
            )
            continue
        proposed = decision.visibility
        if proposed is None:
            invalid(entry, "missing visibility")
            continue
        if proposed.mode != "list" and proposed.characters:
            invalid(entry, "only list mode accepts character names")
            continue
        try:
            names = resolve_character_names(plan.scene, proposed.characters)
        except ValueError as exc:
            invalid(entry, str(exc))
            continue
        if proposed.mode == "list" and not names:
            invalid(entry, "list audience must name existing characters")
            continue
        visibility = EntryVisibility(mode=proposed.mode, characters=names)
        if visibility != entry.visibility:
            plan.proposals.append((entry, visibility, decision.reason))
        else:
            plan.feedback.append(f"Unchanged {entry.label}: {decision.reason}")


class VisibilityAssessmentMixin:
    @set_processing
    async def assess_entry_visibility(
        self, selection: VisibilitySelection
    ) -> VisibilityAssessment:
        scene = self.scene
        entries = await select_visibility_entries(scene, selection)
        budget = min(self.client.max_token_length, MAX_ASSESSMENT_TOKENS)
        response_budget = max(1, min(MAX_RESPONSE_TOKENS, budget // 3))
        history_budget = max(0, min(MAX_HISTORY_TOKENS, budget // 4))
        plan = VisibilityAssessment(
            scene, assessment_context(scene, history_budget), entries
        )
        eligible = []
        for entry in entries:
            if entry.visibility.mode != "everyone" and not selection.reassess:
                plan.feedback.append(
                    f"Preserved {entry.label}: intentional restriction; explicitly request reassessment to include it."
                )
            elif not entry.text.strip():
                plan.feedback.append(f"Unchanged {entry.label}: no content to assess.")
            else:
                eligible.append(entry)
        if not eligible:
            return plan
        if len(eligible) > MAX_ASSESSMENT_ENTRIES:
            raise VisibilityAssessmentError(
                f"Assessment has {len(eligible)} eligible entries; the limit is {MAX_ASSESSMENT_ENTRIES}. Split the world selection or use manual Known by editing for this character. Nothing was assessed or changed."
            )
        prompt = Prompt.get(
            "director.assess-entry-visibility",
            {
                "context": plan.context,
                "entries": [],
                "instructions": selection.instructions,
                "reassess": selection.reassess,
            },
        )
        prompt.client = self.client
        prompt.dedupe_enabled = bool(getattr(self.client, "dedupe_enabled", False))
        handler = SECTION_FORMAT_TO_HANDLER.get(
            getattr(self.client, "section_format", None)
        )
        if handler:
            prompt.sectioning_handler = handler
        if count_tokens(prompt.render()) > budget - response_budget:
            raise VisibilityAssessmentError(
                "The fixed assessment instructions and story context exceed the client context budget. Increase Context Length or shorten the story context/instructions; reducing the entry selection alone cannot help. Nothing was changed."
            )
        prompt.vars["entries"] = [entry.payload() for entry in eligible]
        if count_tokens(prompt.render(force=True)) > budget - response_budget:
            raise VisibilityAssessmentError(
                "Selected content exceeds the assessment budget; narrow the selection or shorten the entries. Nothing was changed."
            )
        prompt.data_expected = True
        response, _ = await prompt.send(
            self.client, make_kind("analyze", response_budget, expect_json=True)
        )
        plan.require_current(self.scene)
        try:
            try:
                data = json.loads(response.strip())
            except ValueError:
                _, data = extract_json(fix_faulty_json(response))
        except (ValueError, TypeError) as exc:
            log.warning("visibility_assessment_invalid_json", error=str(exc))
            raise VisibilityAssessmentError(
                "Assessment returned invalid JSON; nothing was changed. Request a new assessment or edit Known by manually."
            ) from exc
        collect_visibility_decisions(plan, eligible, data)
        return plan

    async def apply_visibility_assessment(self, plan: VisibilityAssessment) -> str:
        plan.require_current(self.scene)
        plan.consumed = True
        for entry, visibility, _ in plan.proposals:
            if entry.kind == "world_entries":
                await plan.scene.world_state_manager.set_world_entry_visibility(
                    entry.key, visibility
                )
            else:
                await plan.scene.world_state_manager.set_character_entry_visibility(
                    entry.owner, entry.key, visibility
                )
        return plan.report(applied=True)
