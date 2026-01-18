import structlog
from typing import Any, Callable, Awaitable
from contextvars import ContextVar

from talemate.agents.base import set_processing, AgentAction, AgentActionConfig
from talemate.emit import emit
from talemate.events import UserInteractionEvent
import talemate.emit.async_signals as async_signals
import talemate.util as util
from talemate.scene_message import (
    CharacterMessage,
    NarratorMessage,
)

from talemate.agents.director.action_core import utils as action_utils
from talemate.agents.director.action_core.exceptions import (
    ActionRejected,
    UnknownAction,
)

from .schema import (
    SceneDirection,
    SceneDirectionMessage,
    SceneDirectionActionResultMessage,
    UserInteractionMessage,
    SceneDirectionBudgets,
    SceneDirectionTurnBalance,
)

log = structlog.get_logger("talemate.agent.director.scene_direction")

# Constants for turn balance tracking
TURN_BALANCE_LOOKBACK_MESSAGES = 10
TURN_BALANCE_NARRATOR_OVERUSE_THRESHOLD = 0.6  # 60% narrator messages
TURN_BALANCE_NARRATOR_NEGLECT_THRESHOLD = 0.2  # <20% narrator messages is neglected
TURN_BALANCE_CHARACTER_NEGLECT_THRESHOLD = (
    0.15  # Character with <15% participation is neglected
)

# Constants for user agency reminders
USER_AGENCY_DIRECTOR_TURNS_THRESHOLD = (
    3  # Director turns before reminding about user participation
)
USER_AGENCY_MIN_USER_TURNS = 1  # Minimum user turns to avoid reminder

# Store whether a scene-direction turn is in progress
scene_direction_context: ContextVar[dict] = ContextVar(
    "scene_direction_context", default={}
)


class SceneDirectionMixin:
    """
    Agent mixin that provides scene direction management stored in scene agent state.

    Storage layout in scene.agent_state:
        scene.agent_state["director"]["scene_direction"] = SceneDirection.model_dump()
    """

    SCENE_DIRECTION_STATE_KEY = "scene_direction"

    @classmethod
    def add_scene_direction_actions(cls, actions: dict[str, AgentAction]):
        actions["scene_direction"] = AgentAction(
            enabled=False,
            container=True,
            can_be_disabled=True,
            quick_toggle=True,
            label="Scene Direction",
            icon="mdi-movie-play",
            description="Automatically perform scene direction using the same actions that are available in the director chat. A strong LLM (100B+), preferably with reasoning capabilities, is HIGHLY recommended for this to work in any meaningful way.",
            config={
                "enable_analysis": AgentActionConfig(
                    type="bool",
                    label="Enable Analysis Step",
                    description="Director does additional analysis before responding.",
                    value=True,
                ),
                "response_length": AgentActionConfig(
                    type="number",
                    label="Response token budget",
                    description="Maximum response length for director responses.",
                    value=2048,
                    step=256,
                    min=512,
                    max=4096,
                ),
                "max_actions_per_turn": AgentActionConfig(
                    type="number",
                    label="Max actions per turn",
                    description="Maximum number of actions to execute per scene direction turn.",
                    value=5,
                    step=1,
                    min=1,
                    max=20,
                ),
                "missing_response_retry_max": AgentActionConfig(
                    type="number",
                    label="Retries",
                    description="How often to retry on malformed director responses.",
                    value=1,
                    step=1,
                    min=1,
                    max=10,
                ),
                "scene_context_ratio": AgentActionConfig(
                    type="number",
                    label="Scene context ratio",
                    description="Fraction of remaining token budget (after fixed context/instructions) reserved for scene context. The rest is for direction history. Example: 0.3 = 30% scene, 70% history.",
                    value=0.3,
                    step=0.05,
                    min=0.05,
                    max=0.95,
                ),
                "staleness_threshold": AgentActionConfig(
                    type="number",
                    label="Stale history share",
                    description="When compacting, fraction of the history budget treated as stale to summarize. The remainder is kept verbatim as recent tail. Higher values summarize less often but bigger chunks.",
                    value=0.7,
                    step=0.05,
                    min=0.05,
                    max=0.95,
                ),
                "custom_instructions": AgentActionConfig(
                    type="blob",
                    label="Custom instructions",
                    description="Custom instructions to add to the scene direction.",
                    value="",
                ),
                "maintain_turn_balance": AgentActionConfig(
                    type="bool",
                    label="Maintain turn balance",
                    description="Track and report participation balance between narrator and active characters to encourage variety in scene direction.",
                    value=True,
                ),
            },
        )

    # === Config property helpers ===

    @property
    def direction_missing_response_retry_max(self) -> int:
        return int(
            self.actions["scene_direction"].config["missing_response_retry_max"].value
        )

    @property
    def direction_response_length(self) -> int:
        return int(self.actions["scene_direction"].config["response_length"].value)

    @property
    def direction_max_actions_per_turn(self) -> int:
        return int(self.actions["scene_direction"].config["max_actions_per_turn"].value)

    @property
    def direction_scene_context_ratio(self) -> float:
        return self.actions["scene_direction"].config["scene_context_ratio"].value

    @property
    def direction_enable_analysis(self) -> bool:
        return self.actions["scene_direction"].config["enable_analysis"].value

    @property
    def direction_staleness_threshold(self) -> float:
        return self.actions["scene_direction"].config["staleness_threshold"].value

    @property
    def direction_custom_instructions(self) -> str:
        return self.actions["scene_direction"].config["custom_instructions"].value

    @property
    def direction_maintain_turn_balance(self) -> bool:
        return self.actions["scene_direction"].config["maintain_turn_balance"].value

    @property
    def direction_enabled(self) -> bool:
        return self.actions["scene_direction"].enabled

    @property
    def direction_enabled_with_override(self) -> bool:
        """
        Check if scene direction is enabled, considering both agent-level
        setting and scene-level override.
        """
        if self.direction_enabled:
            return True

        # Check scene-level override
        if self.scene and self.scene.intent_state:
            return self.scene.intent_state.direction.always_on

        return False

    def connect(self, scene):
        """Connect scene direction signal handlers."""
        super().connect(scene)
        async_signals.get("user_interaction").connect(
            self.on_user_interaction_for_scene_direction
        )

    async def on_user_interaction_for_scene_direction(
        self, emission: UserInteractionEvent
    ):
        """
        Handler for user interactions when scene direction is enabled.
        Appends user interaction to scene direction history.
        """
        if not self.direction_enabled_with_override:
            return

        user_input = emission.message

        # Create user interaction message
        message = UserInteractionMessage(
            user_input=user_input,
        )
        try:
            log.debug("director.scene_direction.user_interaction", message=message)
            await self.direction_append_message(message)
        except Exception as e:
            log.error("director.scene_direction.user_interaction.error", error=e)

    # === State management ===

    def direction_get_state(self) -> dict[str, Any] | None:
        """Return the scene direction state dict if present, else None."""
        state = self.get_scene_state(self.SCENE_DIRECTION_STATE_KEY, default=None)
        return state

    def direction_set_state(self, state: dict[str, Any] | None):
        self.set_scene_states(**{self.SCENE_DIRECTION_STATE_KEY: state})

    def direction_get(self) -> SceneDirection | None:
        raw = self.direction_get_state()
        if not raw:
            return None
        try:
            return raw if isinstance(raw, SceneDirection) else SceneDirection(**raw)
        except Exception as e:
            log.error("director.direction.get.error", error=e)
            return None

    def direction_create(self) -> SceneDirection:
        """Create a scene direction state if none exists; otherwise return the existing one."""
        raw = self.direction_get_state()
        if raw:
            return raw if isinstance(raw, SceneDirection) else SceneDirection(**raw)
        direction = SceneDirection(messages=[])
        self.direction_set_state(direction.model_dump())
        return direction

    def direction_clear(self) -> bool:
        """Clear all messages from the scene direction state."""
        raw = self.direction_get_state()
        if not raw:
            return False
        try:
            direction = (
                raw if isinstance(raw, SceneDirection) else SceneDirection(**raw)
            )
            direction.messages = []
        except Exception:
            return False
        self.direction_set_state(direction.model_dump())
        return True

    # === Message management ===

    def direction_history(
        self,
    ) -> list[
        SceneDirectionMessage
        | SceneDirectionActionResultMessage
        | UserInteractionMessage
    ]:
        direction = self.direction_get()
        return direction.messages if direction else []

    def _direction_emit_history(self, direction: SceneDirection):
        """
        Emit a websocket passthrough event with the entire direction history.
        """
        try:
            messages = direction.messages or []
            visible_messages = [m for m in messages if m.type != "user_interaction"]
            emit(
                "director",
                message="",
                data={
                    "scene_direction_protocol": True,
                    "action": "scene_direction_history",
                    "direction_id": direction.id,
                    "messages": [m.model_dump() for m in visible_messages],
                    "token_total": sum(util.count_tokens(str(m)) for m in messages),
                },
                websocket_passthrough=True,
            )
        except Exception:
            # best-effort; don't break direction turns due to websocket issues
            return

    def _direction_emit_append(
        self, direction: SceneDirection, new_messages: list[Any]
    ) -> None:
        """
        Emit a websocket passthrough event for newly appended direction messages.
        """
        try:
            visible_new_messages = [
                m for m in (new_messages or []) if m.type != "user_interaction"
            ]
            if not visible_new_messages:
                return
            emit(
                "director",
                message="",
                data={
                    "scene_direction_protocol": True,
                    "action": "scene_direction_append",
                    "direction_id": direction.id,
                    "messages": [m.model_dump() for m in visible_new_messages],
                    "token_total": sum(
                        util.count_tokens(str(m)) for m in (direction.messages or [])
                    ),
                },
                websocket_passthrough=True,
            )
        except Exception:
            # best-effort; don't break direction turns due to websocket issues
            return

    def _direction_emit_compacting(self, direction: SceneDirection) -> None:
        """
        Emit a websocket passthrough signal when compaction starts.
        """
        try:
            emit(
                "director",
                message="",
                data={
                    "scene_direction_protocol": True,
                    "action": "scene_direction_compacting",
                    "direction_id": direction.id,
                },
                websocket_passthrough=True,
            )
        except Exception:
            return

    async def direction_append_message(
        self,
        message: SceneDirectionMessage
        | SceneDirectionActionResultMessage
        | UserInteractionMessage,
        on_update: Callable[
            [
                list[
                    SceneDirectionMessage
                    | SceneDirectionActionResultMessage
                    | UserInteractionMessage
                ]
            ],
            Awaitable[None],
        ]
        | None = None,
    ):
        direction: SceneDirection = self.direction_get()
        if not direction:
            direction = self.direction_create()
        direction.messages.append(message)
        self.direction_set_state(direction.model_dump())
        # Always emit a websocket update for UI consumers (read-only feed)
        self._direction_emit_append(direction, [message])
        if on_update:
            await on_update([message])
        return direction

    # === Helper methods ===

    def _direction_compute_user_agency_metrics(self) -> dict:
        """
        Compute user agency metrics from direction history.

        Returns a dict with:
        - user_turn_count: Number of user interactions in history
        - director_turn_count: Number of director turns in history
        - should_remind: Whether to show user agency reminder
        """
        direction = self.direction_get()
        if not direction or not direction.messages:
            return {
                "user_turn_count": 0,
                "director_turn_count": 0,
                "should_remind": False,
            }

        user_turn_count = 0
        director_turn_count = 0

        for message in direction.messages:
            if message.type == "user_interaction":
                user_turn_count += 1
            elif message.type == "text":
                director_turn_count += 1

        # Remind if director has taken enough turns without sufficient user participation
        should_remind = (
            director_turn_count >= USER_AGENCY_DIRECTOR_TURNS_THRESHOLD
            and user_turn_count < USER_AGENCY_MIN_USER_TURNS
        )

        return {
            "user_turn_count": user_turn_count,
            "director_turn_count": director_turn_count,
            "should_remind": should_remind,
        }

    def _direction_compute_turn_balance(self) -> SceneDirectionTurnBalance:
        """
        Compute turn-balance metrics analyzing the last N messages in the scene.

        This tracks participation of the narrator and active characters to encourage
        variety in scene direction actions.
        """
        scene = self.scene
        if not scene or not scene.history:
            return SceneDirectionTurnBalance()

        # Get active characters in the scene (excluding player character)
        active_character_names = [
            char.name for char in scene.characters if not char.is_player
        ]

        # No point tracking turn balance if there are no active non-player characters
        if not active_character_names:
            return SceneDirectionTurnBalance()

        # Track recent messages
        narrator_count = 0
        character_counts: dict[str, int] = {name: 0 for name in active_character_names}
        total_analyzed = 0

        # Analyze last N messages
        for idx in range(len(scene.history) - 1, -1, -1):
            if total_analyzed >= TURN_BALANCE_LOOKBACK_MESSAGES:
                break

            message = scene.history[idx]

            if isinstance(message, NarratorMessage):
                narrator_count += 1
                total_analyzed += 1
            elif isinstance(message, CharacterMessage):
                # Skip player messages
                if message.source == "player":
                    continue

                char_name = message.character_name
                # Track this character even if not in active list
                if char_name not in character_counts:
                    character_counts[char_name] = 0
                character_counts[char_name] += 1
                total_analyzed += 1

        # Calculate percentages
        narrator_percentage = (
            (narrator_count / total_analyzed * 100) if total_analyzed > 0 else 0.0
        )
        character_percentages = {
            name: (count / total_analyzed * 100) if total_analyzed > 0 else 0.0
            for name, count in character_counts.items()
        }

        # Determine if narrator is overused or neglected
        narrator_overused = (
            narrator_percentage >= (TURN_BALANCE_NARRATOR_OVERUSE_THRESHOLD * 100)
            and total_analyzed >= 3
        )
        narrator_neglected = (
            narrator_percentage < (TURN_BALANCE_NARRATOR_NEGLECT_THRESHOLD * 100)
            and total_analyzed >= 3
        )

        # Identify neglected characters
        # A character is neglected if their participation is below the threshold percentage
        neglected_characters = [
            name
            for name in active_character_names
            if character_percentages.get(name, 0)
            < (TURN_BALANCE_CHARACTER_NEGLECT_THRESHOLD * 100)
        ]

        return SceneDirectionTurnBalance(
            total_messages_analyzed=total_analyzed,
            narrator_message_count=narrator_count,
            narrator_percentage=narrator_percentage,
            narrator_overused=narrator_overused,
            narrator_neglected=narrator_neglected,
            character_message_counts=character_counts,
            character_percentages=character_percentages,
            neglected_characters=neglected_characters,
            active_character_names=active_character_names,
        )

    def _direction_create_message(
        self, message: str, source: str = "director", **kwargs
    ) -> SceneDirectionMessage:
        """Factory method for creating direction messages."""
        return SceneDirectionMessage(message=message, source=source, **kwargs)

    def _direction_create_result(self, **kwargs) -> SceneDirectionActionResultMessage:
        """Factory method for creating action result messages."""
        return SceneDirectionActionResultMessage(**kwargs)

    def _direction_create_budgets(self) -> SceneDirectionBudgets:
        """Create budgets for this direction session."""
        return SceneDirectionBudgets(
            max_tokens=self.client.max_token_length,
            scene_context_ratio=self.direction_scene_context_ratio,
        )

    def _serialize_direction_message(
        self, message: Any
    ) -> (
        SceneDirectionMessage
        | SceneDirectionActionResultMessage
        | UserInteractionMessage
        | None
    ):
        """Normalize a direction message into a Pydantic model."""
        try:
            if isinstance(message, dict):
                msg_type = message.get("type", "text")
                if msg_type == "action_result":
                    return SceneDirectionActionResultMessage(**message)
                elif msg_type == "user_interaction":
                    return UserInteractionMessage(**message)
                else:
                    return SceneDirectionMessage(**message)
            return message
        except Exception as e:
            log.error("director.direction.serialize_history.error", error=e)
            return None

    def direction_history_for_prompt(
        self,
    ) -> list[Any]:
        """Prepare direction history for the prompt template."""
        direction = self.direction_get()
        if not direction:
            return []
        return action_utils.serialize_history(
            direction.messages, self._serialize_direction_message
        )

    # === Generation ===

    @set_processing
    async def direction_execute_turn(
        self,
        on_action_complete: Callable[
            [SceneDirectionActionResultMessage], Awaitable[None]
        ]
        | None = None,
        always_on: bool = False,
        max_actions: int | None = None,
    ) -> tuple[list[SceneDirectionActionResultMessage], bool]:
        """
        Execute a scene direction turn - analyze the scene and perform any needed actions.

        Args:
            on_action_complete: Optional callback for each action completed
            always_on: If True, override enabled check and always execute
            max_actions: Optional override for max actions per turn (None = use agent config)

        Returns:
            tuple: (actions_taken, yield_to_user)
                - actions_taken: List of action result messages
                - yield_to_user: Whether to yield control back to user
        """
        if not always_on and not self.direction_enabled_with_override:
            return [], False

        # Set context to indicate we're in a direction turn
        ctx = scene_direction_context.get()
        ctx["in_direction_turn"] = True
        scene_direction_context.set(ctx)

        try:
            return await self._direction_generate(
                on_action_complete=on_action_complete,
                max_actions=max_actions,
            )
        finally:
            ctx = scene_direction_context.get()
            ctx["in_direction_turn"] = False
            scene_direction_context.set(ctx)

    async def _direction_generate(
        self,
        on_action_complete: Callable[
            [SceneDirectionActionResultMessage], Awaitable[None]
        ]
        | None = None,
        max_actions: int | None = None,
    ) -> tuple[list[SceneDirectionActionResultMessage], bool]:
        """
        Internal: Generate a scene direction response and execute actions.

        Args:
            on_action_complete: Optional callback for each action completed
            max_actions: Optional override for max actions per turn (None = use agent config)

        Returns:
            tuple: (actions_taken, yield_to_user)
        """
        # Ensure we have a direction state
        self.direction_create()

        scene_snapshot = self.scene.snapshot(lines=15) if hasattr(self, "scene") else ""

        actions_taken: list[SceneDirectionActionResultMessage] = []
        yield_to_user = False

        # Direction-specific template variables
        turn_balance = self._direction_compute_turn_balance()
        user_agency = self._direction_compute_user_agency_metrics()
        extra_vars = {
            "direction_enable_analysis": self.direction_enable_analysis,
            "custom_instructions": self.direction_custom_instructions,
            "direction_history_trim": action_utils.reverse_trim_history,
            "turn_balance": turn_balance,
            "maintain_turn_balance": self.direction_maintain_turn_balance,
            "user_agency": user_agency,
        }

        # Build prompt vars
        budgets = self._direction_create_budgets()
        prompt_vars = await action_utils.build_prompt_vars(
            scene=self.scene,
            client=self.client,
            history_for_prompt=self.direction_history_for_prompt(),
            scene_snapshot=scene_snapshot,
            budgets=budgets,
            enable_analysis=self.direction_enable_analysis,
            scene_context_ratio=self.direction_scene_context_ratio,
            history_trim_fn=action_utils.reverse_trim_history,
            extra_vars=extra_vars,
            mode="scene_direction",
        )

        kind = f"direction_{self.direction_response_length}"
        max_retries = (
            self.direction_missing_response_retry_max
            if self.direction_enable_analysis
            else 0
        )

        # Make request
        # Scene direction uses DECISION as primary output instead of MESSAGE
        parsed_response, actions_selected, _raw = await action_utils.request_and_parse(
            client=self.client,
            prompt_template="director.scene-direction",
            kind=kind,
            prompt_vars=prompt_vars,
            max_retries=max_retries,
            response_section="decision",
        )

        log.debug(
            "director.direction.actions_selected",
            actions_selected=actions_selected,
        )

        # Append the director's analysis/reasoning if present
        if parsed_response:
            await self.direction_append_message(
                SceneDirectionMessage(message=parsed_response, source="director"),
            )

        # Execute actions if any
        if actions_selected:
            # Limit actions to max_actions_per_turn (use override if provided, otherwise config)
            max_actions_limit = (
                max_actions
                if max_actions is not None
                else self.direction_max_actions_per_turn
            )
            if len(actions_selected) > max_actions_limit:
                actions_selected = actions_selected[:max_actions_limit]

            try:
                action_results = await self._direction_execute_actions(
                    actions_selected, on_action_complete
                )
                actions_taken.extend(action_results)
            except UnknownAction as e:
                log.error("director.direction.actions.execute.unknown_action", error=e)
                error_result = SceneDirectionActionResultMessage(
                    name=e.action_name,
                    result=f"Error executing actions: {e}",
                    instructions=e.action_name,
                    status="error",
                )
                await self.direction_append_message(error_result)
                actions_taken.append(error_result)
            except ActionRejected as e:
                rejected_result = SceneDirectionActionResultMessage(
                    name=e.action_name,
                    result=f"User rejected the following action: {e}",
                    instructions=e.action_name,
                    status="rejected",
                )
                await self.direction_append_message(rejected_result)
                actions_taken.append(rejected_result)
                yield_to_user = True
            except Exception as e:
                log.error("director.direction.actions.execute.error", error=e)
                error_result = SceneDirectionActionResultMessage(
                    name="ERROR",
                    result=f"Error executing actions: {e}",
                    instructions="ERROR",
                    status="error",
                )
                await self.direction_append_message(error_result)
                actions_taken.append(error_result)

            # check shared node state for `_scene_direction_yield_to_user`
            if (
                self.scene.nodegraph_state.shared.get("_scene_direction_yield_to_user")
                is True
            ):
                yield_to_user = True
                # unset the shared node state
                self.scene.nodegraph_state.shared.pop("_scene_direction_yield_to_user")
        else:
            # No actions selected - yield to user
            yield_to_user = True

        # Compact if needed
        try:
            direction_state = self.direction_get()

            async def on_compacting():
                if direction_state:
                    self._direction_emit_compacting(direction_state)

            async def on_compacted(new_messages):
                # After compaction, emit a full history refresh to keep frontend in sync
                refreshed = self.direction_get()
                if refreshed:
                    self._direction_emit_history(refreshed)

            await self._direction_compact_if_needed(
                budgets, on_compacted=on_compacted, on_compacting=on_compacting
            )
        except Exception as e:
            log.error("director.direction.compact.error", error=e)

        return actions_taken, yield_to_user

    # === Compaction ===

    async def _direction_compact_if_needed(
        self,
        budgets_snapshot: SceneDirectionBudgets | None,
        on_compacted: Callable[
            [list[SceneDirectionMessage | SceneDirectionActionResultMessage]],
            Awaitable[None],
        ]
        | None = None,
        on_compacting: Callable[[], Awaitable[None]] | None = None,
    ) -> bool:
        """Compact direction history if needed."""
        direction = self.direction_get()
        if not direction or not direction.messages or not budgets_snapshot:
            return False

        def set_messages(new_messages):
            direction.messages = new_messages
            self.direction_set_state(direction.model_dump())

        async def wrapped_on_compacted(new_messages):
            if on_compacted:
                await on_compacted(new_messages)

        async def wrapped_on_compacting():
            if on_compacting:
                await on_compacting()

        return await action_utils.compact_if_needed(
            messages=direction.messages,
            budgets=budgets_snapshot,
            staleness_threshold=self.direction_staleness_threshold,
            create_message=self._direction_create_message,
            set_messages=set_messages,
            on_compacted=wrapped_on_compacted,
            on_compacting=wrapped_on_compacting,
        )

    # === Action execution ===

    async def _direction_execute_actions(
        self,
        actions_selected: list[dict],
        on_action_complete: Callable[
            [SceneDirectionActionResultMessage], Awaitable[None]
        ]
        | None = None,
    ) -> list[SceneDirectionActionResultMessage]:
        """Execute selected actions via FOCAL, append results to direction history."""
        action_results: list[SceneDirectionActionResultMessage] = []

        async def on_complete(action_msg: SceneDirectionActionResultMessage):
            action_results.append(action_msg)
            # Persist and emit per-action so the frontend sees progress live
            await self.direction_append_message(action_msg)
            if on_action_complete:
                await on_action_complete(action_msg)

        await action_utils.execute_actions(
            client=self.client,
            scene=self.scene,
            actions_selected=actions_selected,
            history_for_prompt=self.direction_history_for_prompt(),
            create_result=self._direction_create_result,
            on_action_complete=on_complete,
        )

        # direction_append_message already persists per-action
        return action_results
