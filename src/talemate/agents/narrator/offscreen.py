from typing import TYPE_CHECKING

import structlog

import talemate.emit.async_signals as async_signals
from talemate.agents.base import AgentAction, AgentActionConfig
from talemate.context import scene_is_loading
from talemate.emit import emit
from talemate.exceptions import GenerationCancelled
from talemate.knowledge.bucket import KnowledgeIndex
from talemate.knowledge.chronology import ranked_facts, render_fact
from talemate.knowledge.topics import known_bucket
from talemate.knowledge.facts import store_offscreen_fact
from talemate.knowledge.processing import evidence_writer
from talemate.knowledge.transitions import (
    absence_seconds,
    latest_transition,
    offscreen_eligible,
    offscreen_status,
    transition_current,
    transitions_enabled,
)
from talemate.prompts import Prompt
from talemate.util.time import duration_to_human

if TYPE_CHECKING:
    from talemate.events import CharacterActivatedEvent
    from talemate.scene_message import CharacterTransitionMessage
    from talemate.tale_mate import Character

log = structlog.get_logger(__name__)


class OffscreenLifeMixin:
    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["offscreen_life"] = AgentAction(
            enabled=False,
            container=True,
            can_be_disabled=True,
            icon="mdi-account-clock-outline",
            label="Offscreen Life",
            description="Add what a returning character did while away to their return entry. One request per return with intervening story or scene time. Enabled by Thorough effort and above; off at Balanced and below.",
            config={
                "length": AgentActionConfig(
                    type="number",
                    label="Length",
                    description="Token length for the offscreen account.",
                    value=192,
                    min=32,
                    max=1024,
                    step=32,
                ),
            },
        )

    @property
    def offscreen_life_enabled(self) -> bool:
        return self.resolve_enabled("offscreen_life")

    @property
    def offscreen_life_length(self) -> int:
        return int(self.resolve_config("offscreen_life", "length"))

    def connect(self, scene):
        super().connect(scene)
        async_signals.get("character.activated").connect(self.on_character_activated)

    async def on_character_activated(self, event: "CharacterActivatedEvent"):
        if event.scene is not self.scene or scene_is_loading.get() is event.scene:
            return
        transition = latest_transition(self.scene, event.character.name)
        if (
            self.offscreen_life_enabled
            and transition is not None
            and transitions_enabled(self.scene)
            and offscreen_eligible(self.scene, transition)
            and transition_current(self.scene, transition)
            and offscreen_status(self.scene, transition) not in ("pending", "ready")
        ):
            await self.narrate_offscreen_life(event.character, transition)

    @evidence_writer
    async def narrate_offscreen_life(
        self, character: "Character", transition: "CharacterTransitionMessage"
    ):
        scene = self.scene
        if (
            not self.offscreen_life_enabled
            or not transitions_enabled(scene)
            or not offscreen_eligible(scene, transition)
            or not transition_current(scene, transition)
            or offscreen_status(scene, transition) in ("pending", "ready")
        ):
            return None

        def inputs():
            return (
                character.name,
                transition.arrival_note,
                absence_seconds(scene, transition),
                scene.cancel_sequence,
            )

        generation_inputs = inputs()

        def current():
            return (
                self.scene is scene
                and transition_current(scene, transition)
                and inputs() == generation_inputs
            )

        transition.offscreen_status = "pending"
        scene.emit_history_message(transition)
        scene.saved = False
        try:
            await scene.attempt_auto_save()
            length = self.offscreen_life_length
            seconds = absence_seconds(scene, transition)
            _, extracted = await Prompt.request(
                "narrator.offscreen-life",
                self.client,
                f"narrate_{length}",
                vars={
                    "scene": scene,
                    "max_tokens": self.client.max_token_length,
                    "character": character,
                    "knowledge_index": KnowledgeIndex.from_scene(scene),
                    "known_facts": [
                        render_fact(scene, fact)
                        for fact in ranked_facts(
                            scene,
                            known_bucket(scene, character.name),
                            limit=12,
                            character=character.name,
                        )
                    ],
                    "elapsed": duration_to_human(seconds, suffix="")
                    if seconds
                    else "an absence with no recorded duration",
                    "extra_instructions": self.extra_instructions,
                    "response_length": length,
                },
            )
            text = self.clean_result(
                (extracted.get("response") or "").strip().strip("*"),
                ensure_dialog_format=False,
                force_narrative=False,
            )
            if not current():
                return None
            if not text:
                raise ValueError("Offscreen Life returned no readable account")
            fact = await store_offscreen_fact(
                scene, character.name, text, still_current=current
            )
            if fact is None:
                return None
            transition.offscreen_fact_id = fact.id
            transition.offscreen_status = "ready"
            return fact
        except (Exception, GenerationCancelled) as exc:
            log.warning(
                "offscreen life failed", character=character.name, error=str(exc)
            )
            if current():
                transition.offscreen_status = "failed"
                emit(
                    "status",
                    status="error",
                    message=f"Offscreen Life for {character.name} failed. The return transition is still available.",
                )
            return None
        finally:
            if transition.offscreen_status == "pending":
                transition.offscreen_status = "failed"
            if self.scene is scene and transition_current(scene, transition):
                scene.saved = False
                scene.emit_history_message(transition)
                await scene.attempt_auto_save()
