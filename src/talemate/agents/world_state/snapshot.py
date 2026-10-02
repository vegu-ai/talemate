from __future__ import annotations

import asyncio
from contextvars import ContextVar
import re
import time
import traceback
from typing import Any, Awaitable, Callable, Iterable, Literal, TYPE_CHECKING

import pydantic
import structlog

import talemate.emit.async_signals
from talemate.emit import emit
from talemate.events import GameLoopActorIterEvent
from talemate.decisions.characters import referenced_characters
from talemate.exceptions import GenerationCancelled
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.snapshots import (
    prepare_snapshot_patch,
    prepare_snapshot_views,
    snapshot_audience_context,
    snapshot_digest,
    snapshot_example,
    snapshot_views_example,
)
from talemate.prompts import Prompt
from talemate.agents.world_state.response_specs import EXAMINE_SPEC
from talemate.scene_message import SceneMessage, TimePassageMessage
from talemate.world_state import INTRO_ANCHOR_ID, WorldStateResponse
from talemate.world_state.merge import (
    apply_bucket_patch,
    cap_bucket,
    has_time_passage_boundary,
)
from talemate.util.prompt import condensed
from talemate.world_state.schema import CharacterState, ObjectState, PlaceState
from talemate.world_state.snapshot_revision import (
    IncompatibleSnapshotTemplate,
    SnapshotRequest,
    SnapshotRevision,
    can_publish,
    retain_previous,
)

from talemate.agents.base import (
    AgentAction,
    AgentActionConfig,
    AgentActionConditional,
    AgentEmission,
    set_processing,
)

if TYPE_CHECKING:
    from talemate.world_state import WorldState

log = structlog.get_logger("talemate.agents.world_state")

# Message types skipped while `current_moment` walks scene.history
# collecting focus lines. Every focus message ends up in `anchor_message_ids`
# and can render inline highlights — so anything kept in this list is excluded
# from the focus span and gets no highlights. `context_investigation` is the
# soft case: the `include_context_investigation` config knob removes it from
# the per-call ignore set when enabled.
WORLD_STATE_SNAPSHOT_IGNORE = [
    "reinforcement",
    "director",
    "context_investigation",
    "character_transition",
]

# Opaque key for the world state snapshot's tracked single-flight task
# (Agent.run_tracked_task) — internal, not user-facing. The manual add shares
# the key so the user's explicit action takes over the slot the refresh uses,
# and the panel's existing spinner and cancel button drive it unchanged.
SNAPSHOT_TASK = "world_state_update"
# set inside the work of the tracked snapshot task: its awaited child tasks
# (a listener graph's RunModule) inherit it, send_soon listeners do not
_snapshot_slot_held = ContextVar("snapshot_slot_held", default=None)
talemate.emit.async_signals.detach_in_listener_tasks(_snapshot_slot_held)


async def _in_snapshot_slot(work: Callable[[], Awaitable]):
    token = _snapshot_slot_held.set(True)
    try:
        return await work()
    finally:
        _snapshot_slot_held.reset(token)


# Longest text selection accepted by the manual add. The frontend mirrors it in
# talemate_frontend/src/utils/messageSelection.js.
SNAPSHOT_ENTITY_SELECTION_MAX = 240

SNAPSHOT_ENTITY_BUCKETS: dict[str, tuple[str, type]] = {
    "character": ("characters", CharacterState),
    "item": ("items", ObjectState),
    "place": ("places", PlaceState),
}


talemate.emit.async_signals.register("agent.world_state.snapshot.entity_added")


class SnapshotEntityAddition(pydantic.BaseModel):
    """Outcome of a manual snapshot add, for the caller to report."""

    resolved: bool = False
    waiting_for_regeneration: bool = False
    name: str = ""
    kind: Literal["", "character", "item", "place"] = ""
    in_moment: bool = False
    mentions: list[str] = pydantic.Field(default_factory=list)

    @property
    def highlighted(self) -> bool:
        return self.in_moment and bool(self.mentions)


class SnapshotEntityAddedEmission(AgentEmission):
    """A selected character, item or place was added to the world snapshot."""

    message_id: int
    selection: str
    name: str
    kind: Literal["character", "item", "place"]
    in_moment: bool
    mentions: list[str]


class CurrentMoment(pydantic.BaseModel):
    """The focus span of a snapshot: the newest messages, oldest first, and
    the scene intro when it falls inside the span."""

    messages: list[SceneMessage] = pydantic.Field(default_factory=list)
    intro: str = ""

    @property
    def anchor_ids(self) -> list[int]:
        intro = [INTRO_ANCHOR_ID] if self.intro else []
        return [*intro, *(message.id for message in self.messages)]


def occurs_as_words(haystack: str, needle: str) -> bool:
    """True when `needle` occurs in `haystack` on word boundaries."""
    return bool(
        re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack, re.IGNORECASE)
    )


def match_existing_name(name: str, candidates: Iterable[str]) -> str | None:
    """
    The name among ``candidates`` that ``name`` refers to: the same name
    ignoring case, else one that contains the other on word boundaries
    ("Horn" onto "Kestrel's Horn"). ``None`` when nothing matches.
    """
    lowered = name.lower()
    candidates = list(candidates)
    for candidate in candidates:
        if candidate.lower() == lowered:
            return candidate
    for candidate in candidates:
        if occurs_as_words(candidate, name) or occurs_as_words(name, candidate):
            return candidate
    return None


def resolve_character_name(
    world_state: "WorldState", character_names: list[str], raw_name: str
) -> str:
    """
    Map a raw character name from a model response onto the scene's canonical
    name: normalized casing first, then the scene's name synonyms, then a
    substring match against the cast.

    The cast is a closed, authoritative set, so the loose tail is safe here in
    a way it is not against a snapshot bucket: it is what folds "Sam" onto
    "Samuel" and "Bobby" onto "Bob" instead of opening a second row for one
    person.
    """
    name = world_state.normalize_name(raw_name)
    for main_name, synonyms in world_state.character_name_mappings.items():
        if name.lower() in synonyms:
            name = main_name
            break
    if name not in character_names:
        for canonical in character_names:
            if canonical.lower() in name.lower() or name.lower() in canonical.lower():
                name = canonical
                break
    return name


def normalize_snapshot_selection(text: str) -> str:
    return condensed(text or "").strip()


def message_body(message: SceneMessage) -> str:
    """
    The message text as the client renders it. A character message keeps its
    ``"Name: "`` prefix in storage but not on screen, so a phrase that occurs
    only in the prefix could never become a highlight.
    """
    body = getattr(message, "without_name", None)
    return body if isinstance(body, str) else str(message)


def literal_mentions(message_text: str, raw_mentions: Any, selection: str) -> list[str]:
    """
    Keep the mention phrases that occur in the message on word boundaries —
    the same test the client's highlight parser applies, so a phrase that
    fails it here could never become a highlight there.

    Model phrases rank above the selection; the selection is the last resort,
    including when the model returned a bare string, which would otherwise
    spread into single letters.
    """

    def occurs(phrase: str) -> bool:
        return bool(
            re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", message_text, re.IGNORECASE)
        )

    kept: list[str] = []
    seen: set[str] = set()
    candidates = raw_mentions if isinstance(raw_mentions, list) else []
    for phrase in candidates:
        if not isinstance(phrase, str):
            continue
        phrase = normalize_snapshot_selection(phrase)
        key = phrase.lower()
        if not phrase or key in seen or not occurs(phrase):
            continue
        seen.add(key)
        kept.append(phrase)

    if not kept and selection and occurs(selection):
        kept.append(selection)

    return kept


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
                "audience_decision_model": AgentActionConfig(
                    type="bool",
                    label="Use Decision Model for Snapshot Audiences",
                    description="Recognize off-stage characters mentioned by pronoun, title or nickname when building perspectives. Adds one quick decision request per snapshot with off-stage characters to check; unclear or failed answers use name matching.",
                    value=True,
                ),
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
                    description="How many of the most recent messages count as the current moment. These messages can show inline entity highlights. While the scene has fewer messages than this, the scene intro takes a spare line, unless a time passage lies between the intro and the newest messages.",
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

    async def audience_context_with_references(self, scene, budget, focus_text=""):
        names = await referenced_characters(
            scene,
            focus_text,
            [
                name
                for name in scene.character_data
                if name not in scene.active_characters
            ],
            uid="world_state.decision-snapshot-references",
            enabled=self.resolve_config(
                "update_world_state", "audience_decision_model"
            ),
            match=lambda name: bool(
                re.search(rf"(?<!\w){re.escape(name)}(?!\w)", focus_text, re.IGNORECASE)
            ),
            is_current=lambda: self.scene is scene,
        )
        return snapshot_audience_context(scene, budget, referenced_names=names)

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
        so we run it synchronously (foreground) instead. Character perspectives
        never run it in the background: its character views are knowledge, and
        knowledge work runs one request at a time.
        """
        return bool(
            self.client
            and self.client.supports_concurrent_inference
            and not character_knowledge_enabled(self.scene)
        )

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

        try:
            await self.dispatch_world_state_update(
                wait=character_knowledge_enabled(self.scene)
            )
        except GenerationCancelled:
            # no turn runs yet at scene start; the cancel ends only the snapshot
            pass
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
        if not await self.dispatch_world_state_update(
            wait=character_knowledge_enabled(self.scene)
        ):
            return

        self.next_update = 0

    async def dispatch_world_state_update(
        self, cancel_in_flight: bool = False, instructions: str = "", wait: bool = False
    ) -> bool:
        """
        Run the world state snapshot as a single-flight tracked task. Returns
        True if a generation was started, False if one was already in flight.

        Runs in the background (status "busy_bg", non-blocking UI) when the
        linked client supports concurrent inference; otherwise in the foreground
        (status "busy") so the user doesn't queue an action behind it on a client
        that can't serve concurrent requests. The call returns at once unless
        ``wait`` is set: then it returns when the snapshot has finished, a
        cancelled caller cancels the snapshot, and a Cancel or Stop during the
        snapshot raises ``GenerationCancelled``.

        ``cancel_in_flight=True`` cancels a running snapshot and starts a fresh
        one — used by the manual refresh, where the user's explicit action
        (especially a reset) should take priority over an in-progress run.

        ``instructions`` is one-off guidance for this pass only.
        """
        scene = self.scene
        cancel_sequence = scene.cancel_sequence
        task = await self.run_tracked_task(
            SNAPSHOT_TASK,
            lambda: _in_snapshot_slot(
                lambda: scene.world_state.request_update(instructions=instructions)
            ),
            background=self.snapshot_runs_in_background,
            cancel_in_flight=cancel_in_flight,
            error_handler=self.on_world_state_error,
        )
        running = task or self._tracked_task(SNAPSHOT_TASK)
        if wait and running is not None:
            try:
                # its failures are reported by the tracked task's callback
                await asyncio.wait([running])
            except asyncio.CancelledError:
                running.cancel()
                raise
            user_cancelled = (
                not running.cancelled()
                and running.exception() is None
                and running.result() == "cancelled"
            )
            if user_cancelled or scene.cancel_sequence != cancel_sequence:
                raise GenerationCancelled(
                    "World state update was cancelled", by_user=True
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

    def cut_snapshot_at_time_passage(self, world_state: "WorldState") -> bool:
        """
        Apply the scene cut a TimePassage since the last snapshot calls for:
        wipe the snapshot the way a refresh does, and leave the current moment
        as the anchors, which is the watermark ``has_time_passage_boundary``
        reads. Returns True when it cut.

        Runs before the request rather than after it, so the model is shown the
        buckets the merge will write into.
        """
        if not self.update_world_state_durable_snapshot:
            return False
        if not has_time_passage_boundary(
            self.scene.history, world_state.anchor_message_ids
        ):
            return False

        world_state.characters = {}
        world_state.items = {}
        world_state.places = {}
        world_state.location = None
        world_state.location_perspectives = None
        world_state.anchor_message_ids = self.current_moment().anchor_ids
        world_state.snapshot_provenance = None
        world_state.previous_snapshot = None
        world_state._snapshot_epoch += 1
        return True

    @property
    def can_add_snapshot_entity(self) -> bool:
        """Whether the agent can serve a manual add at all."""
        return bool(self.enabled and self.update_world_state_enabled and self.client)

    async def dispatch_add_snapshot_entity(self, message_id: int, text: str) -> bool:
        """
        Run the manual add as a tracked task under the snapshot's single-flight
        key, cancelling an in-flight refresh: the user asked for this entity, so
        it takes the slot. Returns True when a task was started.
        """
        if not self.can_add_snapshot_entity:
            return False

        task = await self.run_tracked_task(
            SNAPSHOT_TASK,
            lambda: _in_snapshot_slot(
                lambda: self.add_and_report_snapshot_entity(message_id, text)
            ),
            background=self.snapshot_runs_in_background,
            cancel_in_flight=True,
            error_handler=self.on_add_snapshot_entity_error,
        )
        return task is not None

    async def add_snapshot_entity_in_slot(
        self, message_id: int, text: str
    ) -> SnapshotEntityAddition:
        """
        The manual add under the snapshot's single-flight key, cancelling an
        in-flight refresh as the UI add does, awaited for its result. Called
        from inside the snapshot work (a listener of its events), it adds
        directly.
        """
        if _snapshot_slot_held.get():
            return await self.add_snapshot_entity(message_id, text)

        async def add():
            # a refused selection is the caller's error, not a failed task
            try:
                return await self.add_snapshot_entity(message_id, text)
            except ValueError as exc:
                return exc

        task = await self.run_tracked_task(
            SNAPSHOT_TASK,
            lambda: _in_snapshot_slot(add),
            background=False,
            cancel_in_flight=True,
        )
        result = await task
        if isinstance(result, ValueError):
            raise result
        return result

    async def on_add_snapshot_entity_error(self, error: Exception):
        # A scene change or a user cancel is a quiet stop, not a failure —
        # the refresh path swallows the same exception.
        if isinstance(error, (GenerationCancelled, asyncio.CancelledError)):
            return
        if isinstance(error, IncompatibleSnapshotTemplate):
            emit("status", str(error), status="error")
            return
        emit("status", "Adding to the world state failed.", status="error")
        log.error("add_snapshot_entity", error=error)

    async def add_and_report_snapshot_entity(self, message_id: int, text: str):
        """Run the manual add and tell the user what came of it."""
        result = await self.add_snapshot_entity(message_id, text)

        if result.waiting_for_regeneration:
            emit(
                "status",
                "Wait for message regeneration to finish before adding to the world snapshot.",
                status="info",
            )
            return

        if not result.resolved:
            emit(
                "status",
                "That selection did not resolve to a character, item or place.",
                status="warning",
            )
            return

        if result.highlighted:
            emit(
                "status",
                f"Added {result.name} to the world state.",
                status="success",
            )
        elif not result.in_moment:
            emit(
                "status",
                f"Added {result.name} to the world state. The message is outside "
                "the current moment, so it shows no inline highlight.",
                status="info",
            )
        else:
            emit(
                "status",
                f"Added {result.name} to the world state. No phrase of the "
                "message could be marked, so it shows no inline highlight.",
                status="info",
            )

    @set_processing
    async def add_snapshot_entity(
        self, message_id: int, text: str
    ) -> SnapshotEntityAddition:
        """
        Resolve a user-selected span of text into one snapshot entry and merge
        it into the current snapshot.

        One analytical request. The entry goes in through the same patch path
        the refresh uses — never a rebuild — and is stamped ``manual``, which
        exempts it from auto-eviction and from being dropped by the item cap.
        The model may refuse: a selection that names no distinct entity comes
        back unresolved and nothing is written.
        """
        scene = self.scene
        world_state = scene.world_state
        if world_state._snapshot_regenerating:
            world_state.emit()
            return SnapshotEntityAddition(waiting_for_regeneration=True)
        selection = normalize_snapshot_selection(text)

        if not selection:
            raise ValueError("add_snapshot_entity requires a non-empty selection")

        if len(selection) > SNAPSHOT_ENTITY_SELECTION_MAX:
            raise ValueError(
                f"Selection is longer than {SNAPSHOT_ENTITY_SELECTION_MAX} characters"
            )

        message = scene.get_message(message_id)
        if message is None:
            raise ValueError(f"No scene message with id {message_id}")

        before = SnapshotRevision.capture(world_state)
        snapshot_request = SnapshotRequest(
            scene,
            template="world_state/add-snapshot-entity.jinja2",
            includes_director=self.long_term_memory_enabled
            or message.typ == "director",
        )
        perception = character_knowledge_enabled(scene)
        audience_context = (
            await self.audience_context_with_references(
                scene, max(1, self.client.max_token_length // 4), str(message)
            )
            if perception
            else None
        )

        # Membership of the current moment is the live walk, not the anchors the
        # last refresh left behind — every message pushed since then would read
        # as outside the moment, including the one the user just read.
        in_moment = message.id in {m.id for m in self.current_moment().messages}

        # Only an entry that belongs to the current moment carries the scene cut
        # with it. An entry added from a message before the cut belongs to the
        # moment the cut ends, so the snapshot and its watermark are left alone
        # and the next refresh cuts both it and the rest away.
        if in_moment:
            self.cut_snapshot_at_time_passage(world_state)
        epoch = world_state._snapshot_epoch

        # The panel raises its spinner and its cancel button on the "requested"
        # status and lowers them on the next frame, so every exit from here has
        # to emit one.
        world_state.emit(status="requested")
        try:
            result = await self._resolve_and_merge_snapshot_entity(
                scene,
                world_state,
                message,
                selection,
                perception,
                audience_context,
                in_moment,
                epoch,
                snapshot_request,
            )
            if result.resolved:
                retain_previous(
                    world_state, before, snapshot_request.verified_provenance(), scene
                )
        finally:
            world_state.emit()
        if result.resolved:
            await talemate.emit.async_signals.get(
                "agent.world_state.snapshot.entity_added"
            ).send(
                SnapshotEntityAddedEmission(
                    agent=self,
                    message_id=message.id,
                    selection=selection,
                    name=result.name,
                    kind=result.kind,
                    in_moment=result.in_moment,
                    mentions=list(result.mentions),
                )
            )
        return result

    async def _resolve_and_merge_snapshot_entity(
        self,
        scene,
        world_state: "WorldState",
        message: SceneMessage,
        selection: str,
        perception: bool,
        audience_context: dict | None,
        in_moment: bool,
        epoch: int,
        snapshot_request: SnapshotRequest,
    ) -> SnapshotEntityAddition:
        _, response = await Prompt.request(
            "world_state.add-snapshot-entity",
            self.client,
            "analyze",
            vars={
                "scene": scene,
                "snapshot_request": snapshot_request,
                "max_tokens": self.client.max_token_length,
                "message_text": message_body(message),
                "selection": selection,
                "tracked_entities": {
                    "characters": list(world_state.characters.keys()),
                    "items": list(world_state.items.keys()),
                    "places": list(world_state.places.keys()),
                },
                "custom_instructions": self.update_world_state_custom_instructions,
                "include_scene_intent": True,
                "include_scenario_premise": True,
                "snapshot_audience_context": audience_context,
                "audience_views_example": snapshot_views_example(audience_context)
                if audience_context
                else None,
            },
        )

        if self.scene is not scene or not can_publish(
            world_state, scene, epoch, snapshot_request.verified_provenance()
        ):
            raise GenerationCancelled("Scene changed while adding a snapshot entity")

        entity = (response or {}).get("entity") if isinstance(response, dict) else None
        if not isinstance(entity, dict) or not entity.get("resolved"):
            return SnapshotEntityAddition()

        kind = str(entity.get("kind") or "").strip().lower()
        raw_name = str(entity.get("name") or "").strip()
        snapshot_text = str(entity.get("snapshot") or "").strip()
        bucket_name, state_class = SNAPSHOT_ENTITY_BUCKETS.get(kind, (None, None))

        if not bucket_name or not raw_name or not snapshot_text:
            log.warning(
                "world_state.add_snapshot_entity: unusable entry", entity=entity
            )
            return SnapshotEntityAddition()

        bucket = getattr(world_state, bucket_name)
        if kind == "character":
            # A name the cast confirms is authoritative. Matching it against the
            # bucket as well would write onto whichever tracked character shares
            # a word with it — "Emma" onto a background "Emma's mother".
            name = resolve_character_name(world_state, scene.character_names, raw_name)
        else:
            # The prompt asks the model to reuse a tracked name, which is a
            # request rather than a guarantee — and a duplicate pin would
            # survive both eviction and the cap.
            name = world_state.normalize_name(raw_name)
            name = match_existing_name(name, bucket) or name

        mentions = literal_mentions(
            message_body(message), entity.get("mentions"), selection
        )
        previous = bucket.get(name)
        if previous is not None:
            # A patch replaces the mentions list, so an entity already tracked
            # would lose the phrases the refresh found in its other focus
            # lines, and with them their highlights.
            carried = [
                phrase
                for phrase in mentions
                if phrase.lower() not in {m.lower() for m in previous.mentions}
            ]
            mentions = [*previous.mentions, *carried]

        payload: dict[str, Any] = {"snapshot": snapshot_text, "mentions": mentions}
        if kind == "character":
            emotion = entity.get("emotion")
            if isinstance(emotion, str) and emotion.strip():
                payload["emotion"] = emotion.strip()
        if perception and isinstance(entity.get("views"), list):
            payload["views"] = entity["views"]

        patch: dict[str, Any] = {name: payload}
        if perception:
            patch = prepare_snapshot_patch(scene, bucket, patch, audience_context)

        merged = apply_bucket_patch(bucket, patch, state_class, mark_manual=True)
        if name not in merged:
            log.error(
                "world_state.add_snapshot_entity: entry was rejected",
                name=name,
                kind=kind,
            )
            return SnapshotEntityAddition()

        # The cap is a durable-mode policy: legacy mode rebuilds every bucket
        # each pass and hides the setting, so enforcing it here would evict
        # entries against a limit the user cannot see.
        if bucket_name == "items" and self.update_world_state_durable_snapshot:
            merged = cap_bucket(merged, self.update_world_state_max_items)
        setattr(world_state, bucket_name, merged)

        # A message in the moment becomes an anchor so the client renders the
        # highlight without waiting for the next refresh.
        if in_moment and message.id not in world_state.anchor_message_ids:
            world_state.anchor_message_ids = [
                *world_state.anchor_message_ids,
                message.id,
            ]

        return SnapshotEntityAddition(
            resolved=True,
            name=name,
            kind=kind,
            in_moment=in_moment,
            mentions=mentions,
        )

    def current_moment(self) -> CurrentMoment:
        """
        The current moment: walk ``scene.history`` backward collecting up to
        ``focus_lines`` narrative messages. When the walk reaches the start of
        the history with lines to spare, the scene intro takes one of them.

        TimePassageMessage is a hard boundary — the moment on the other side is
        a different scene, not what we're highlighting, and the intro lies
        beyond it. Other ignored types (reinforcement, director, ...) are
        skipped without ending the walk. ``context_investigation`` is
        conditionally ignored per the agent config: when off it stays in the
        ignore set; when on it becomes a valid focus candidate that can also
        receive highlights.
        """
        ignore_types = set(WORLD_STATE_SNAPSHOT_IGNORE)
        if self.update_world_state_include_context_investigation:
            ignore_types.discard("context_investigation")

        focus_lines = self.update_world_state_focus_lines
        focus_messages: list = []
        for message in reversed(self.scene.history):
            if isinstance(message, TimePassageMessage):
                return CurrentMoment(messages=focus_messages)
            if message.typ in ignore_types:
                continue
            focus_messages.insert(0, message)
            if len(focus_messages) >= focus_lines:
                return CurrentMoment(messages=focus_messages)
        return CurrentMoment(messages=focus_messages, intro=self.scene.get_intro())

    @set_processing
    async def request_world_state(self, instructions: str = "") -> WorldStateResponse:
        scene = self.scene
        snapshot_request = SnapshotRequest(
            scene,
            template="world_state/request-world-state-v2.jinja2",
            includes_director=self.long_term_memory_enabled,
        )
        moment = self.current_moment()

        # Nothing to anchor highlights to. Silently return an empty response so
        # the world_state holder re-emits current state and no LLM call is made.
        if not moment.messages and not moment.intro:
            return WorldStateResponse()

        t1 = time.time()

        durable_snapshot = self.update_world_state_durable_snapshot
        audience_context = (
            await self.audience_context_with_references(
                scene,
                max(1, self.client.max_token_length // 4),
                "\n".join(
                    [
                        *([moment.intro] if moment.intro else []),
                        *(str(message) for message in moment.messages),
                    ]
                ),
            )
            if character_knowledge_enabled(scene)
            else None
        )

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
                    name: char.model_dump(
                        exclude={"mentions", "misses", "perspectives", "manual"}
                    )
                    for name, char in ws.characters.items()
                },
                "items": {
                    name: obj.model_dump(
                        exclude={"mentions", "misses", "perspectives", "manual"}
                    )
                    for name, obj in ws.items.items()
                },
                "places": {
                    name: place.model_dump(
                        exclude={"mentions", "misses", "perspectives", "manual"}
                    )
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
                "snapshot_request": snapshot_request,
                "max_tokens": self.client.max_token_length,
                "object_type": "character",
                "object_type_plural": "characters",
                "scene_focus": moment.messages,
                "intro_text": moment.intro,
                "include_scene_intent": True,
                "include_scenario_premise": True,
                "durable_snapshot": durable_snapshot,
                "current_state_payload": current_state_payload,
                "custom_instructions": self.update_world_state_custom_instructions,
                "instructions": instructions,
                "snapshot_audience_context": audience_context,
                "snapshot_audience_example": snapshot_example(
                    audience_context, durable_snapshot
                )
                if audience_context
                else None,
            },
        )

        if self.scene is not scene:
            raise GenerationCancelled("Scene changed during snapshot generation")

        self.scene.log.debug(
            "request_world_state",
            response=world_state,
            anchor_message_ids=moment.anchor_ids,
            time=time.time() - t1,
        )

        return WorldStateResponse(
            world_state=world_state,
            anchor_message_ids=moment.anchor_ids,
            audience_context=audience_context,
            provenance=snapshot_request.verified_provenance(),
        )

    async def apply_snapshot_update(
        self, world_state: "WorldState", instructions: str = ""
    ) -> Literal["cancelled"] | None:
        """
        Generate a fresh world-state snapshot and merge it into ``world_state``.
        Returns "cancelled" when the user cancelled it (Stop, or Cancel in the
        error dialog), so every caller waiting for the snapshot task sees it.

        Owns the snapshot policy: the scene-cut wipe, the LLM call
        (``request_world_state``), name normalization, the durable
        delta-merge vs legacy wholesale-rebuild choice, eviction/capping, and
        the surrounding ``emit`` status transitions. ``WorldState.request_update``
        is the thin public entry point that delegates here.
        """
        scene = self.scene

        if world_state._snapshot_regenerating:
            world_state.emit()
            return
        before = SnapshotRevision.capture(world_state)
        epoch = world_state._snapshot_epoch
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
            world_state.location_perspectives = None
            world_state.anchor_message_ids = []

        world_state.emit(status="requested")

        try:
            response = await self.request_world_state(instructions=instructions)
        except IncompatibleSnapshotTemplate as error:
            world_state.emit()
            emit("status", str(error), status="error")
            return
        except GenerationCancelled as exc:
            world_state.emit()
            if exc.by_user or scene.cancel_requested:
                return "cancelled"
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

        provenance = response.provenance
        if self.scene is not scene or not can_publish(
            world_state, scene, epoch, provenance
        ):
            world_state.emit()
            return

        raw = response.world_state
        character_names = scene.character_names

        # Normalize bucket keys against canonical scene names. Values stay
        # as raw dicts (or None) so the delta-merge path can preserve the
        # null-to-drop semantic.
        char_patch: dict[str, Any] = {
            resolve_character_name(world_state, character_names, raw_name): payload
            for raw_name, payload in (raw.get("characters") or {}).items()
        }

        item_patch: dict[str, Any] = {
            world_state.normalize_name(name): payload
            for name, payload in (raw.get("items") or {}).items()
        }
        place_patch: dict[str, Any] = {
            world_state.normalize_name(name): payload
            for name, payload in (raw.get("places") or {}).items()
        }

        perception = character_knowledge_enabled(scene)
        if perception:
            char_patch = prepare_snapshot_patch(
                scene, world_state.characters, char_patch, response.audience_context
            )
            item_patch = prepare_snapshot_patch(
                scene, world_state.items, item_patch, response.audience_context
            )
            place_patch = prepare_snapshot_patch(
                scene, world_state.places, place_patch, response.audience_context
            )

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
                if (
                    perception
                    and "snapshot" not in char_kwargs
                    and name in world_state.characters
                ):
                    char_kwargs["snapshot"] = world_state.characters[name].snapshot
                preserve_emotion = (
                    "emotion" not in char_kwargs
                    if perception
                    else not char_kwargs.get("emotion")
                )
                if preserve_emotion and name in world_state.characters:
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
                    if (
                        perception
                        and "snapshot" not in payload
                        and name in world_state.items
                    ):
                        payload = {
                            "snapshot": world_state.items[name].snapshot,
                            **payload,
                        }
                    new_items[name] = ObjectState(**payload)
                except Exception as e:
                    log.error("world_state.apply_snapshot_update", error=e, item=name)
            new_places: dict[str, PlaceState] = {}
            for name, payload in place_patch.items():
                if not payload or not isinstance(payload, dict):
                    continue
                try:
                    if (
                        perception
                        and "snapshot" not in payload
                        and name in world_state.places
                    ):
                        payload = {
                            "snapshot": world_state.places[name].snapshot,
                            **payload,
                        }
                    new_places[name] = PlaceState(**payload)
                except Exception as e:
                    log.error("world_state.apply_snapshot_update", error=e, place=name)
            world_state.characters = new_chars
            world_state.items = new_items
            world_state.places = new_places

        valid_location = "location" not in raw or isinstance(
            raw["location"], (str, type(None))
        )
        if "location" in raw and (perception or valid_location):
            if valid_location:
                world_state.location = raw["location"]
            world_state.location_perspectives = None
        if perception and valid_location and "location_views" in raw:
            world_state.location_perspectives = prepare_snapshot_views(
                scene,
                raw["location_views"],
                snapshot_digest("location", world_state.location),
                response.audience_context,
            )

        world_state.anchor_message_ids = list(response.anchor_message_ids)
        retain_previous(world_state, before, provenance, scene)

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
            response_spec=EXAMINE_SPEC,
        )

        return extracted["response"].strip()
