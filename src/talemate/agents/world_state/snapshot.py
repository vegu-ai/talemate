from __future__ import annotations

import asyncio
import time
import traceback
from typing import Any, TYPE_CHECKING

import structlog

import talemate.emit.async_signals
from talemate.emit import emit
from talemate.events import GameLoopActorIterEvent
from talemate.exceptions import GenerationCancelled
from talemate.prompts import Prompt
from talemate.prompts.response import AnchorExtractor, ResponseSpec
from talemate.scene_message import TimePassageMessage
from talemate.world_state import WorldStateResponse
from talemate.world_state.merge import (
    apply_bucket_patch,
    cap_bucket,
    has_time_passage_boundary,
)
from talemate.world_state.schema import CharacterState, ObjectState, PlaceState

from talemate.agents.base import (
    AgentAction,
    AgentActionConfig,
    AgentActionConditional,
    set_processing,
)

if TYPE_CHECKING:
    from talemate.world_state import WorldState

log = structlog.get_logger("talemate.agents.world_state")

# Message types skipped while `request_world_state` walks scene.history
# collecting focus lines. Every focus message ends up in `anchor_message_ids`
# and can render inline highlights — so anything kept in this list is excluded
# from the focus span and gets no highlights. `context_investigation` is the
# soft case: the `include_context_investigation` config knob removes it from
# the per-call ignore set when enabled.
WORLD_STATE_SNAPSHOT_IGNORE = [
    "reinforcement",
    "director",
    "context_investigation",
]

# Opaque key for the world state snapshot's tracked single-flight task
# (Agent.run_tracked_task) — internal, not user-facing.
SNAPSHOT_TASK = "world_state_update"


class WorldStateSnapshotMixin:
    """
    World-state manager agent mixin that handles world state snapshot updates
    (the periodic refresh of the tracked characters/items/places) and the
    in-fiction "examine" expansion of snapshot entities.
    """

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["update_world_state"] = AgentAction(
            enabled=True,
            can_be_disabled=True,
            container=True,
            icon="mdi-earth",
            label="Update world state",
            quick_toggle=True,
            description="Will attempt to update the world state based on the current scene. Runs automatically every N character turns.",
            config={
                "initial": AgentActionConfig(
                    type="bool",
                    label="When a new scene is started",
                    description="Whether to update the world state on scene start.",
                    value=True,
                ),
                "turns": AgentActionConfig(
                    type="number",
                    label="Turns",
                    description="Number of character turns (player or AI) to wait before updating the world state.",
                    value=10,
                    min=1,
                    max=100,
                    step=1,
                ),
                "focus_lines": AgentActionConfig(
                    type="number",
                    label="Lines in the moment",
                    description="How many of the most recent messages count as the current moment. These messages can show inline entity highlights.",
                    value=3,
                    min=1,
                    max=10,
                    step=1,
                ),
                "include_context_investigation": AgentActionConfig(
                    type="bool",
                    label="Include Look at / Add Detail",
                    description="When on, Look at and Add Detail messages also count as part of the current moment and can show inline highlights.",
                    value=False,
                ),
                "custom_instructions": AgentActionConfig(
                    type="blob",
                    label="Custom instructions",
                    description="Custom instructions to add to the world state snapshot generation.",
                    value="",
                ),
                "examine_length": AgentActionConfig(
                    type="number",
                    label="Add Detail length",
                    description="How long an Add Detail result can be. Shorter lengths keep the generated description tighter; longer lengths allow more elaboration.",
                    value=256,
                    min=32,
                    max=1024,
                    step=32,
                ),
                "inject_as_scene_memory": AgentActionConfig(
                    type="bool",
                    label="Pin to context",
                    description="Pin the world state snapshot into the conversation and narrator prompts as live scene memory.",
                    value=False,
                ),
                "durable_snapshot": AgentActionConfig(
                    type="bool",
                    label="Durable snapshot",
                    quick_toggle=True,
                    description="Keep entities and their details across refreshes so the world state builds up over time. When off, every refresh starts from scratch.",
                    value=True,
                ),
                "max_items": AgentActionConfig(
                    type="number",
                    label="Max items tracked",
                    description="Maximum number of items the snapshot can hold at once. When a refresh exceeds this, the stalest items are dropped. Set to 0 for no limit.",
                    value=10,
                    min=0,
                    max=30,
                    step=1,
                    condition=AgentActionConditional(
                        attribute="update_world_state.config.durable_snapshot",
                        value=True,
                    ),
                ),
                "eviction_threshold": AgentActionConfig(
                    type="number",
                    label="Auto-evict stale entries",
                    description="Automatically drop a snapshot entry the agent leaves unchanged for this many consecutive world state updates, guarding against stale entries the agent fails to remove on its own. Set to 0 to disable.",
                    value=3,
                    min=0,
                    max=20,
                    step=1,
                    condition=AgentActionConditional(
                        attribute="update_world_state.config.durable_snapshot",
                        value=True,
                    ),
                ),
            },
        )

    # config property helpers

    @property
    def initial_update(self):
        return self.resolve_config("update_world_state", "initial")

    @property
    def update_world_state_enabled(self) -> bool:
        return self.resolve_enabled("update_world_state")

    @property
    def update_world_state_turns(self) -> int:
        return self.resolve_config("update_world_state", "turns")

    @property
    def update_world_state_focus_lines(self) -> int:
        return self.resolve_config("update_world_state", "focus_lines")

    @property
    def update_world_state_include_context_investigation(self) -> bool:
        return self.resolve_config(
            "update_world_state", "include_context_investigation"
        )

    @property
    def update_world_state_examine_length(self) -> int:
        return self.resolve_config("update_world_state", "examine_length")

    @property
    def update_world_state_custom_instructions(self) -> str:
        return self.resolve_config("update_world_state", "custom_instructions")

    @property
    def update_world_state_max_items(self) -> int:
        return self.resolve_config("update_world_state", "max_items")

    @property
    def update_world_state_durable_snapshot(self) -> bool:
        return self.resolve_config("update_world_state", "durable_snapshot")

    @property
    def update_world_state_eviction_threshold(self) -> int:
        return self.resolve_config("update_world_state", "eviction_threshold")

    @property
    def snapshot_runs_in_background(self) -> bool:
        """
        Whether the snapshot should run as a true background task. Only when the
        linked client can handle a concurrent request — otherwise a background
        snapshot would just contend with the main generation on the same client,
        so we run it synchronously (foreground) instead.
        """
        return bool(self.client and self.client.supports_concurrent_inference)

    # signal connect

    def connect(self, scene):
        super().connect(scene)
        talemate.emit.async_signals.get("game_loop_actor_iter").connect(
            self.on_game_loop_actor_iter
        )
        talemate.emit.async_signals.get("scene_loop_init_after").connect(
            self.on_scene_loop_init_after
        )

    async def on_scene_loop_init_after(self, emission):
        """
        Called when a scene is initialized
        """
        if not self.enabled:
            return

        if not self.initial_update:
            return

        if self.get_scene_state("inital_update_done"):
            return

        await self.dispatch_world_state_update()
        self.set_scene_states(inital_update_done=True)

    async def on_game_loop_actor_iter(self, emission: GameLoopActorIterEvent):
        """
        Called after each actor (player or AI) has had a turn.
        """

        if not self.enabled:
            return

        await self.update_world_state()

    # methods

    async def update_world_state(self, force: bool = False):
        if not self.enabled:
            return

        if not self.update_world_state_enabled:
            return

        log.debug(
            "update_world_state",
            next_update=self.next_update,
            turns=self.update_world_state_turns,
        )

        if (
            self.next_update % self.update_world_state_turns != 0
            or self.next_update == 0
        ) and not force:
            self.next_update += 1
            return

        # Single-flight: if a snapshot is still generating, leave the counter at
        # its due value and retry next turn rather than starting an overlapping
        # run (which would race on scene.world_state and double the eviction
        # counter). dispatch returns False when one is already in flight.
        if not await self.dispatch_world_state_update():
            return

        self.next_update = 0

    async def dispatch_world_state_update(self, cancel_in_flight: bool = False) -> bool:
        """
        Run the world state snapshot as a single-flight tracked task. Returns
        True if a generation was started, False if one was already in flight.

        Runs in the background (status "busy_bg", non-blocking UI) when the
        linked client supports concurrent inference; otherwise in the foreground
        (status "busy") so the user doesn't queue an action behind it on a client
        that can't serve concurrent requests. Either way the call is non-blocking.

        ``cancel_in_flight=True`` cancels a running snapshot and starts a fresh
        one — used by the manual refresh, where the user's explicit action
        (especially a reset) should take priority over an in-progress run.
        """
        task = await self.run_tracked_task(
            SNAPSHOT_TASK,
            lambda: self.scene.world_state.request_update(),
            background=self.snapshot_runs_in_background,
            cancel_in_flight=cancel_in_flight,
            error_handler=self.on_world_state_error,
        )
        return task is not None

    def cancel_world_state_update(self) -> bool:
        """
        Cancel an in-flight snapshot. Returns True if one was running and got
        cancelled. request_update clears the "requested" status on cancellation
        so the UI spinner resolves.
        """
        return self.cancel_tracked_task(SNAPSHOT_TASK)

    async def on_world_state_error(self, error: Exception):
        emit("status", "World state update failed.", status="error")
        log.error("update_world_state", error=error)

    @set_processing
    async def request_world_state(self) -> WorldStateResponse:
        # Walk scene.history backward collecting up to `focus_lines` narrative
        # messages. TimePassageMessage is a hard boundary — the moment on the
        # other side is a different scene, not what we're highlighting. Other
        # ignored types (reinforcement, director, ...) are skipped without
        # ending the walk. `context_investigation` is conditionally ignored
        # per the agent config: when off it stays in the ignore set; when on
        # it becomes a valid focus candidate that can also receive highlights.
        focus_lines = self.update_world_state_focus_lines
        ignore_types = set(WORLD_STATE_SNAPSHOT_IGNORE)
        if self.update_world_state_include_context_investigation:
            ignore_types.discard("context_investigation")

        focus_messages: list = []
        for message in reversed(self.scene.history):
            if isinstance(message, TimePassageMessage):
                break
            if message.typ in ignore_types:
                continue
            focus_messages.insert(0, message)
            if len(focus_messages) >= focus_lines:
                break

        # Fall back to the scene intro only on a fresh scene (no live history).
        # If the walk turned up empty because of a TimePassageMessage boundary
        # or director-only noise, the scene has already moved past the intro —
        # using it as the "current moment" would be wrong.
        intro_text = (
            self.scene.get_intro()
            if not focus_messages and not self.scene.history
            else ""
        )

        # Nothing to anchor highlights to AND no intro to fall back on. Silently
        # return an empty response so the world_state holder re-emits current
        # state and no LLM call is made.
        if not focus_messages and not intro_text:
            return WorldStateResponse()

        # Every focus message is a valid highlight anchor — the frontend
        # applies the parser's mention pass to all of them, so phrases that
        # only appear in an earlier focus line still get highlighted there.
        anchor_message_ids = [m.id for m in focus_messages]

        t1 = time.time()

        durable_snapshot = self.update_world_state_durable_snapshot

        # Pre-build a rendered current-state payload for the prompt's CURRENT
        # STATE section. Only shown in durable mode (legacy mode's prompt
        # framing is fresh-extract, so prior state would just be noise).
        # Mentions are excluded because they're focus-window-specific —
        # forcing the LLM to re-derive them keeps the highlight phrasing
        # current.
        current_state_payload = {}
        if durable_snapshot:
            ws = self.scene.world_state
            current_state_payload = {
                "characters": {
                    name: char.model_dump(exclude={"mentions", "misses"})
                    for name, char in ws.characters.items()
                },
                "items": {
                    name: obj.model_dump(exclude={"mentions", "misses"})
                    for name, obj in ws.items.items()
                },
                "places": {
                    name: place.model_dump(exclude={"mentions", "misses"})
                    for name, place in ws.places.items()
                },
                "location": ws.location,
            }

        _, world_state = await Prompt.request(
            "world_state.request-world-state-v2",
            self.client,
            "analyze_long",
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "object_type": "character",
                "object_type_plural": "characters",
                "scene_focus": focus_messages,
                "intro_text": intro_text,
                "include_scene_intent": True,
                "include_scenario_premise": True,
                "durable_snapshot": durable_snapshot,
                "current_state_payload": current_state_payload,
                "custom_instructions": self.update_world_state_custom_instructions,
            },
        )

        self.scene.log.debug(
            "request_world_state",
            response=world_state,
            anchor_message_ids=anchor_message_ids,
            time=time.time() - t1,
        )

        return WorldStateResponse(
            world_state=world_state, anchor_message_ids=anchor_message_ids
        )

    async def apply_snapshot_update(self, world_state: "WorldState"):
        """
        Generate a fresh world-state snapshot and merge it into ``world_state``.

        Owns the snapshot policy: the scene-cut wipe, the LLM call
        (``request_world_state``), name normalization, the durable
        delta-merge vs legacy wholesale-rebuild choice, eviction/capping, and
        the surrounding ``emit`` status transitions. ``WorldState.request_update``
        is the thin public entry point that delegates here.
        """
        scene = self.scene

        # TimePassageMessage past the prior anchors is a scene cut: wipe the
        # snapshot before showing it to the LLM so the next pass extracts
        # fresh against an empty baseline. Durable mode only — legacy
        # wholesale doesn't need a separate cut because it rewrites every
        # pass anyway.
        if self.update_world_state_durable_snapshot and has_time_passage_boundary(
            scene.history, world_state.anchor_message_ids
        ):
            world_state.characters = {}
            world_state.items = {}
            world_state.places = {}
            world_state.location = None
            world_state.anchor_message_ids = []

        world_state.emit(status="requested")

        try:
            response = await self.request_world_state()
        except GenerationCancelled:
            world_state.emit()
            return
        except asyncio.CancelledError:
            # Background task was cancelled (manual cancel of the in-flight
            # snapshot). Clear the "requested" status so the UI spinner resolves,
            # then let the cancellation propagate so the task ends cancelled.
            world_state.emit()
            raise
        except Exception as e:
            world_state.emit()
            log.error(
                "world_state.apply_snapshot_update",
                error=e,
                traceback=traceback.format_exc(),
            )
            return

        if response.world_state is None:
            world_state.emit()
            return

        raw = response.world_state
        character_names = scene.character_names

        # Normalize bucket keys against canonical scene names. Values stay
        # as raw dicts (or None) so the delta-merge path can preserve the
        # null-to-drop semantic.
        char_patch: dict[str, Any] = {}
        for raw_name, payload in (raw.get("characters") or {}).items():
            name = world_state.normalize_name(raw_name)
            for main_name, synonyms in world_state.character_name_mappings.items():
                if name.lower() in synonyms:
                    name = main_name
                    break
            if name not in character_names:
                for canonical in character_names:
                    if (
                        canonical.lower() in name.lower()
                        or name.lower() in canonical.lower()
                    ):
                        name = canonical
                        break
            char_patch[name] = payload

        item_patch: dict[str, Any] = {
            world_state.normalize_name(name): payload
            for name, payload in (raw.get("items") or {}).items()
        }
        place_patch: dict[str, Any] = {
            world_state.normalize_name(name): payload
            for name, payload in (raw.get("places") or {}).items()
        }

        if self.update_world_state_durable_snapshot:
            # Delta merge: apply patch on top of current state. None values
            # drop the entity; partial dicts patch fields; omitted keys are
            # untouched. Entries the agent leaves untouched for
            # `eviction_threshold` consecutive passes age out automatically.
            eviction_threshold = self.update_world_state_eviction_threshold
            world_state.characters = apply_bucket_patch(
                world_state.characters, char_patch, CharacterState, eviction_threshold
            )
            world_state.items = apply_bucket_patch(
                world_state.items, item_patch, ObjectState, eviction_threshold
            )
            world_state.places = apply_bucket_patch(
                world_state.places, place_patch, PlaceState, eviction_threshold
            )
            # Cap the items bucket, dropping stalest entries first (highest
            # `misses`). Durable-only: in legacy mode every item is rebuilt
            # fresh each pass with misses=0, so "stalest" is meaningless.
            world_state.items = cap_bucket(
                world_state.items, self.update_world_state_max_items
            )
        else:
            # Legacy wholesale: drop None entries (no delete semantic),
            # construct full state classes, replace entire buckets. Preserve
            # emotion when the new pass omits it.
            new_chars: dict[str, CharacterState] = {}
            for name, payload in char_patch.items():
                if not payload or not isinstance(payload, dict):
                    continue
                char_kwargs = dict(payload)
                if not char_kwargs.get("emotion") and name in world_state.characters:
                    char_kwargs["emotion"] = world_state.characters[name].emotion
                try:
                    new_chars[name] = CharacterState(**char_kwargs)
                except Exception as e:
                    log.error(
                        "world_state.apply_snapshot_update", error=e, character=name
                    )
            new_items: dict[str, ObjectState] = {}
            for name, payload in item_patch.items():
                if not payload or not isinstance(payload, dict):
                    continue
                try:
                    new_items[name] = ObjectState(**payload)
                except Exception as e:
                    log.error("world_state.apply_snapshot_update", error=e, item=name)
            new_places: dict[str, PlaceState] = {}
            for name, payload in place_patch.items():
                if not payload or not isinstance(payload, dict):
                    continue
                try:
                    new_places[name] = PlaceState(**payload)
                except Exception as e:
                    log.error("world_state.apply_snapshot_update", error=e, place=name)
            world_state.characters = new_chars
            world_state.items = new_items
            world_state.places = new_places

        if "location" in raw and isinstance(raw["location"], (str, type(None))):
            world_state.location = raw["location"]

        world_state.anchor_message_ids = list(response.anchor_message_ids)

        world_state.emit()

    @set_processing
    async def examine_entity(
        self,
        entity_name: str,
        entity_kind: str,
        snapshot_text: str,
    ) -> str:
        """
        Synthesize an in-fiction "examine" result for a tooltip-highlighted
        entity. Takes the 2-3 sentence snapshot text and expands it into
        grounded prose describing what the player observes about the entity
        at this moment in the scene. Output length is governed by the
        `examine_length` config, which both caps the tokens and scales the
        auto-appended response-length instruction.

        Returns the synthesized text. Caller is responsible for surfacing it
        in the UI — typically as a ContextInvestigationMessage anchored to
        the moment of the examine click. Prior examine results land back in
        scene history, so repeated examines for the same or related entities
        accumulate context naturally via `scene.context_history()`.
        """
        if not snapshot_text or not snapshot_text.strip():
            raise ValueError("examine_entity requires non-empty snapshot_text")

        response_length = self.update_world_state_examine_length

        _, extracted = await Prompt.request(
            "world_state.examine-entity",
            self.client,
            f"create_{response_length}",
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "entity_name": entity_name,
                "entity_kind": entity_kind,
                "snapshot_text": snapshot_text,
                "include_scene_intent": True,
                "include_scenario_premise": True,
            },
            response_spec=ResponseSpec(
                extractors={
                    "response": AnchorExtractor(
                        left="<EXAMINE>",
                        right="</EXAMINE>",
                        fallback_to_full=True,
                    ),
                },
            ),
        )

        return extracted["response"].strip()
