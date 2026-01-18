import asyncio
import traceback

import structlog

log = structlog.get_logger("talemate.server.scene_assets_batching")


class SceneAssetsBatchingMixin:
    """Mixin class for debounced batching of scene asset requests."""

    # Debounce window for batching scene asset requests (in seconds)
    SCENE_ASSETS_BATCH_WINDOW_SECONDS = 0.1

    def _init_scene_assets_batching(self):
        """Initialize scene assets batching state."""
        self._scene_assets_pending_ids: set[str] = set()
        self._scene_assets_batch_handle: asyncio.Handle | None = None
        self._loop = asyncio.get_event_loop()

    def _cleanup_scene_assets_batching(self):
        """Cleanup scene assets batching state (call during disconnect)."""
        if self._scene_assets_batch_handle is not None:
            self._scene_assets_batch_handle.cancel()
            self._scene_assets_batch_handle = None
        self._scene_assets_pending_ids.clear()

    def _send_scene_assets_immediate(self, asset_ids):
        """Send scene assets immediately without batching."""
        scene_assets = self.scene.assets

        try:
            for asset_id in asset_ids:
                asset = scene_assets.get_asset_bytes_as_base64(asset_id)
                if not asset:
                    continue

                self.queue_put(
                    {
                        "type": "scene_asset",
                        "asset_id": asset_id,
                        "asset": asset,
                        "media_type": scene_assets.get_asset(asset_id).media_type,
                    }
                )
        except Exception:
            log.error("_send_scene_assets_immediate", error=traceback.format_exc())

    def _flush_scene_assets_batch(self):
        """Flush pending scene asset requests after batch window expires."""
        # Check if handle was cancelled or cleared (e.g., during disconnect)
        if (
            self._scene_assets_batch_handle is None
            or self._scene_assets_batch_handle.cancelled()
        ):
            self._scene_assets_batch_handle = None
            return

        if not self._scene_assets_pending_ids:
            self._scene_assets_batch_handle = None
            return

        # Snapshot pending IDs and clear the set
        pending = list(self._scene_assets_pending_ids)
        self._scene_assets_pending_ids.clear()
        self._scene_assets_batch_handle = None

        # Send all pending assets
        self._send_scene_assets_immediate(pending)

    def request_scene_assets(self, asset_ids: list[str] | None):
        """
        Request scene assets with debounced batching.

        Multiple requests within SCENE_ASSETS_BATCH_WINDOW_SECONDS will be
        batched together and sent once after the window expires.
        """
        if not asset_ids:
            return

        # Add all requested IDs to the pending set (deduplicates automatically)
        self._scene_assets_pending_ids.update(asset_ids)

        # If no batch timer is active, schedule a flush
        if (
            self._scene_assets_batch_handle is None
            or self._scene_assets_batch_handle.cancelled()
        ):
            self._scene_assets_batch_handle = self._loop.call_later(
                self.SCENE_ASSETS_BATCH_WINDOW_SECONDS, self._flush_scene_assets_batch
            )
