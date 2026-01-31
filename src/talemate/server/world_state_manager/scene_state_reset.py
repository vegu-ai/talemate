from typing import Union

import pydantic
import structlog

log = structlog.get_logger("talemate.server.world_state_manager.scene_state_reset")


class ExecuteSceneStateResetPayload(pydantic.BaseModel):
    reset_context_db: bool = False
    wipe_history: bool = False
    wipe_history_include_static: bool = False
    reset_intent_state: bool = False
    reset_agent_states: dict[str, Union[bool, list[str]]] = pydantic.Field(
        default_factory=dict
    )
    wipe_reinforcements: list[int] = pydantic.Field(default_factory=list)


class SceneStateResetMixin:
    """
    Mixin providing handlers for resetting various scene state components.
    """

    async def handle_get_scene_state_reset_info(self, data: dict):
        """
        Returns current state info to populate the reset dialog.
        """
        scene = self.scene

        # Collect agent states info
        agent_states = {}
        for agent_name, agent_state in scene.agent_state.items():
            if agent_state:  # Only include agents that have state
                agent_states[agent_name] = list(agent_state.keys())

        # Collect reinforcements info
        reinforcements = []
        for idx, reinforcement in enumerate(scene.world_state.reinforce):
            reinforcements.append(
                {
                    "idx": idx,
                    "question": reinforcement.question,
                    "character": reinforcement.character,
                }
            )

        # Count history entries
        history_count = len(scene.history)
        archived_history_count = len(scene.archived_history)
        static_history_count = sum(
            1 for ah in scene.archived_history if ah.get("end") is None
        )
        layered_history_count = len(scene.layered_history)

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "get_scene_state_reset_info",
                "data": {
                    "agent_states": agent_states,
                    "reinforcements": reinforcements,
                    "history_count": history_count,
                    "archived_history_count": archived_history_count,
                    "static_history_count": static_history_count,
                    "layered_history_count": layered_history_count,
                },
            }
        )

    async def handle_execute_scene_state_reset(self, data: dict):
        """
        Executes the reset based on provided configuration.
        """
        payload = ExecuteSceneStateResetPayload(**data)
        scene = self.scene
        reset_summary = []

        # Wipe history
        if payload.wipe_history:
            history_count = len(scene.history)
            archived_count = len(scene.archived_history)
            layered_count = len(scene.layered_history)

            scene.history = []
            scene.layered_history = []

            if payload.wipe_history_include_static:
                scene.archived_history = []
                reset_summary.append(
                    f"Wiped all history ({history_count} messages, {archived_count} archived, {layered_count} layered)"
                )
            else:
                static_entries = [
                    ah for ah in scene.archived_history if ah.get("end") is None
                ]
                removed_count = archived_count - len(static_entries)
                scene.archived_history = static_entries
                reset_summary.append(
                    f"Wiped history ({history_count} messages, {removed_count} archived, {layered_count} layered), kept {len(static_entries)} static entries"
                )

            log.info(
                "Wiped scene history",
                history_count=history_count,
                archived_count=archived_count,
                layered_count=layered_count,
                include_static=payload.wipe_history_include_static,
            )

        # Reset intent state
        if payload.reset_intent_state:
            scene.intent_state.reset()
            reset_summary.append("Reset intent state")
            log.info("Reset intent state")

        # Reset agent states
        if payload.reset_agent_states:
            for agent_name, keys in payload.reset_agent_states.items():
                if agent_name not in scene.agent_state:
                    continue

                if keys is True:
                    # Reset entire agent state
                    del scene.agent_state[agent_name]
                    reset_summary.append(f"Reset all {agent_name} agent state")
                    log.info("Reset entire agent state", agent=agent_name)
                elif isinstance(keys, list):
                    # Reset specific keys
                    for key in keys:
                        if key in scene.agent_state[agent_name]:
                            del scene.agent_state[agent_name][key]
                    reset_summary.append(
                        f"Reset {agent_name} agent state keys: {', '.join(keys)}"
                    )
                    log.info("Reset agent state keys", agent=agent_name, keys=keys)

                    # Clean up empty agent state
                    if not scene.agent_state[agent_name]:
                        del scene.agent_state[agent_name]

        # Wipe reinforcements (process in descending order to preserve indices)
        if payload.wipe_reinforcements:
            sorted_indices = sorted(payload.wipe_reinforcements, reverse=True)
            wiped_count = 0
            for idx in sorted_indices:
                if 0 <= idx < len(scene.world_state.reinforce):
                    await scene.world_state.remove_reinforcement(idx)
                    wiped_count += 1
            reset_summary.append(f"Wiped {wiped_count} reinforcement(s)")
            log.info("Wiped reinforcements", count=wiped_count)

        # Reset context DB (reimport from scene) - done last so it reflects all other changes
        if payload.reset_context_db:
            await scene.commit_to_memory()
            reset_summary.append("Reset context DB (reimported from scene)")
            log.info("Reset context DB")

        self.websocket_handler.queue_put(
            {
                "type": "world_state_manager",
                "action": "execute_scene_state_reset",
                "data": {
                    "success": True,
                    "summary": reset_summary,
                },
            }
        )

        # Emit updates to refresh frontend state
        await self.scene.emit_history()
        self.scene.world_state.emit()
        self.scene.emit_status()

        await self.signal_operation_done()
