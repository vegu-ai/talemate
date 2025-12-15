from __future__ import annotations

import structlog

import talemate.emit.async_signals as async_signals
from talemate.game.engine.ux.schema import UXCancelPayload, UXSelectPayload, UXSelection

from .websocket_plugin import Plugin

__all__ = ["UxPlugin"]

log = structlog.get_logger("talemate.server.ux")

async_signals.register("ux.selected")


class UxPlugin(Plugin):
    """
    Websocket router to support node-driven UX elements.

    Frontend -> backend:
      - { type: "ux", action: "select", ux_id: "...", ... }
      - { type: "ux", action: "cancel", ux_id: "..." }

    Backend stores the selection into:
      scene.nodegraph_state.shared[f"_ux_{ux_id}"] = UXSelection.model_dump()
    """

    router = "ux"

    def _set_selection(self, selection: UXSelection):
        scene = self.scene
        if not scene:
            log.error("ux.no_scene", selection=selection.model_dump())
            return

        graph_state = getattr(scene, "nodegraph_state", None)
        if not graph_state:
            log.error("ux.no_nodegraph_state", selection=selection.model_dump())
            return

        key = f"_ux_{selection.ux_id}"
        log.debug(
            "ux.set_selection",
            ux_id=selection.ux_id,
            key=key,
            cancelled=selection.cancelled,
            choice_id=selection.choice_id,
            selected=selection.selected,
        )
        graph_state.shared[key] = selection.model_dump()

    async def handle_select(self, data: dict):
        payload = UXSelectPayload(**data)
        log.debug(
            "ux.handle_select",
            ux_id=payload.ux_id,
            kind=payload.kind,
            choice_id=payload.choice_id,
            selected=payload.selected,
            value=payload.value,
            label=payload.label,
        )

        selection = UXSelection(
            ux_id=payload.ux_id,
            kind=payload.kind or "choice",
            selected=payload.selected,
            choice_id=payload.choice_id,
            value=payload.value,
            label=payload.label,
            cancelled=False,
            raw=payload.model_dump(),
        )

        self._set_selection(selection)

        try:
            await async_signals.get("ux.selected").send(selection)
        except Exception as exc:
            log.debug("ux.selected.signal_failed", error=str(exc))

    async def handle_cancel(self, data: dict):
        payload = UXCancelPayload(**data)
        log.debug("ux.handle_cancel", ux_id=payload.ux_id, kind=payload.kind)

        selection = UXSelection(
            ux_id=payload.ux_id,
            kind=payload.kind or "choice",
            selected=None,
            cancelled=True,
            raw=payload.model_dump(),
        )

        self._set_selection(selection)

        try:
            await async_signals.get("ux.selected").send(selection)
        except Exception as exc:
            log.debug("ux.cancel.signal_failed", error=str(exc))
