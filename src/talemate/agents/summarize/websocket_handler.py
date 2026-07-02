import pydantic
import structlog

from talemate.agents.summarize.context_history import ContextHistoryPreviewOverrides
from talemate.instance import get_agent
from talemate.server.websocket_plugin import Plugin

__all__ = [
    "SummarizeWebsocketHandler",
]

log = structlog.get_logger("talemate.server.summarize")


class ApplyContextHistoryConfigPayload(pydantic.BaseModel):
    dialogue_ratio: int
    summary_detail_ratio: int
    max_budget: int
    enforce_boundary: bool
    best_fit: bool
    best_fit_min_dialogue: int
    best_fit_max_dialogue: int


class SummarizeWebsocketHandler(Plugin):
    """
    Handles summarize actions
    """

    router = "summarizer"

    @property
    def summarizer(self):
        return get_agent("summarizer")

    async def handle_context_review(self, data: dict):
        scene = self.scene
        if not scene:
            await self.signal_operation_failed("No scene loaded")
            return

        overrides = None
        if "overrides" in data:
            overrides = ContextHistoryPreviewOverrides(**data["overrides"])

        preview = self.summarizer.context_history_preview(scene, overrides=overrides)
        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "context_review",
                "data": preview,
            }
        )

    async def handle_apply_context_history_config(self, data: dict):
        """Apply context history config overrides to the summarizer agent and persist.

        Each field routes through ``write_config`` so any active scene-level
        override receives the new value instead of being silently shadowed by
        a write to the global config it overrides.
        """
        payload = ApplyContextHistoryConfigPayload(**data.get("config", {}))

        for field in (
            "dialogue_ratio",
            "summary_detail_ratio",
            "max_budget",
            "enforce_boundary",
            "best_fit",
            "best_fit_min_dialogue",
            "best_fit_max_dialogue",
        ):
            self.summarizer.write_config(
                "manage_scene_history", field, getattr(payload, field)
            )

        # `write_config` routes per-field: overridden fields land in the
        # overlay, the rest in the global. There's no transaction across the
        # two targets, so we persist both independently and surface an overlay
        # failure to the user without suppressing the global save — otherwise
        # any non-overridden field's edit would be silently lost on restart.
        # Overridden-field edits still revert on next scene load if the
        # overlay write failed.
        overlay_error: OSError | None = None
        overrides = self.summarizer.scene_overrides()
        if overrides is not None:
            try:
                await overrides.write_to_file()
            except OSError as exc:
                log.warning(
                    "scene-overrides write failed",
                    filepath=str(overrides.filepath),
                    error=str(exc),
                )
                overlay_error = exc

        await self.summarizer.save_config()
        await self.summarizer.emit_status()

        if overlay_error is not None:
            await self.signal_operation_failed(
                f"Failed to write agent-settings file: "
                f"{overlay_error.strerror or overlay_error}"
            )
