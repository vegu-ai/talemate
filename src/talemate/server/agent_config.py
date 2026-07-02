"""Websocket plugin for live agent-config mutations.

This plugin handles operations that mutate an agent's stored configuration
outside of the bulk ``configure_agents`` save path — primarily managing the
*dynamic-action registries* (e.g. TTS OpenAI-compatible backends): registering
a child action, unregistering it, renaming its label.

Each handler runs the canonical agent method (which fires lifecycle hooks),
saves the updated agent config to disk, and re-emits the agent status so the
frontend re-renders with the new tab list.
"""

import structlog

from talemate.config import commit_config
from talemate.instance import AGENTS
from talemate.scene_agent_settings import (
    SceneAgentSettings,
    agent_settings_dir,
    is_safe_settings_filename,
)
from talemate.util import slugify

from .websocket_plugin import Plugin

log = structlog.get_logger("talemate.server.agent_config")


class AgentConfigPlugin(Plugin):
    """Live mutations to an agent's stored configuration."""

    router = "agent_config"

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    async def _resolve_registry(self, data: dict):
        """Validate ``agent_type`` + ``action_key`` and return the resolved
        agent. On any failure, surface it via ``signal_operation_failed`` so
        the UI gets feedback, and return ``None``.
        """
        agent_type = data.get("agent_type")
        action_key = data.get("action_key")
        agent = AGENTS.get(agent_type) if agent_type else None
        if not agent:
            msg = f"Agent '{agent_type}' not found"
            log.warning(msg, action=data.get("action"))
            await self.signal_operation_failed(msg)
            return None, None, None
        if not action_key or not agent.is_dynamic_registry(action_key):
            msg = f"'{action_key}' is not a dynamic registry on agent '{agent_type}'"
            log.warning(msg, action=data.get("action"))
            await self.signal_operation_failed(msg)
            return None, None, None
        return agent, agent_type, action_key

    async def _persist_and_broadcast(self, agent) -> None:
        # NOTE: this path runs alongside the bulk ``configure_agents`` save
        # path. Both write to the same ``Config.agents[agent_type]`` slot.
        # We rely on the websocket dispatcher serializing inbound messages so
        # there's no concurrent register-vs-configure overlap on the same
        # agent. If that assumption changes, add a lock.
        await agent.save_config()
        await commit_config()
        await agent.emit_status()

    # ------------------------------------------------------------------
    # handlers
    # ------------------------------------------------------------------

    async def handle_register_child(self, data: dict):
        """Register a new child entry in a dynamic-action registry.

        Required: ``agent_type``, ``action_key``, ``label``.
        Slug is derived server-side via ``util.slugify``; collisions get a
        numeric suffix.
        """
        agent, agent_type, action_key = await self._resolve_registry(data)
        if not agent:
            return

        label = (data.get("label") or "").strip()
        if not label:
            await self.signal_operation_failed("Label is required")
            return

        slug = slugify(label)
        if not slug:
            await self.signal_operation_failed(
                f"Could not derive a slug from label '{label}'"
            )
            return

        existing = set(agent.dynamic_child_slugs(action_key))
        unique_slug, n = slug, 2
        while unique_slug in existing:
            unique_slug = f"{slug}-{n}"
            n += 1

        try:
            agent.register_dynamic_child(action_key, unique_slug, label)
        except ValueError as exc:
            log.warning(
                "agent_config.register_child rejected",
                agent_type=agent_type,
                action_key=action_key,
                slug=unique_slug,
                error=str(exc),
            )
            await self.signal_operation_failed(str(exc))
            return

        await agent.persist_dynamic_external_state(action_key)
        await self._persist_and_broadcast(agent)

    async def handle_unregister_child(self, data: dict):
        """Remove a child entry from a dynamic-action registry.

        Required: ``agent_type``, ``action_key``, ``slug``.
        """
        agent, _, action_key = await self._resolve_registry(data)
        if not agent:
            return

        slug = data.get("slug")
        if not slug:
            await self.signal_operation_failed("Slug is required")
            return

        agent.unregister_dynamic_child(action_key, slug)
        await agent.persist_dynamic_external_state(action_key)
        await self._persist_and_broadcast(agent)

    async def handle_rename_child(self, data: dict):
        """Rename a child entry's label (slug stays frozen).

        Required: ``agent_type``, ``action_key``, ``slug``, ``label``.
        """
        agent, _, action_key = await self._resolve_registry(data)
        if not agent:
            return

        slug = data.get("slug")
        label = (data.get("label") or "").strip()
        if not slug:
            await self.signal_operation_failed("Slug is required")
            return
        if not label:
            await self.signal_operation_failed("Label is required")
            return

        agent.rename_dynamic_child_label(action_key, slug, label)
        await self._persist_and_broadcast(agent)

    # ------------------------------------------------------------------
    # Per-scene agent overrides
    # ------------------------------------------------------------------

    async def handle_save_scene_overrides(self, data: dict):
        """Persist a sparse per-agent override set into the scene's
        agent-settings JSON file.

        Required: ``agent_type``, ``override`` (sparse AgentOverride dict).
        Optional: ``filename`` (creates / re-links the file when supplied;
        used by the modal's first-time naming flow).
        """
        agent_type = data.get("agent_type")
        override = data.get("override")
        filename = data.get("filename")

        agent = AGENTS.get(agent_type) if agent_type else None
        if not agent:
            await self.signal_operation_failed(f"Agent '{agent_type}' not found")
            return

        scene = getattr(agent, "scene", None)
        if scene is None:
            await self.signal_operation_failed(
                f"Agent '{agent_type}' is not connected to a scene"
            )
            return

        # Refuse for unsaved scenes — save_dir would collapse to scenes-root.
        if not scene.filename or not scene.project_name:
            log.warning(
                "scene-overrides save refused: scene has no on-disk identity",
                agent_type=agent_type,
                scene_name=getattr(scene, "name", None),
                project_name=getattr(scene, "project_name", None),
                filename=getattr(scene, "filename", None),
            )
            await self.signal_operation_failed(
                "Save the scene first before adding per-scene agent overrides."
            )
            return

        # Defense against path traversal — filename arrives over the wire
        # and must stay inside ``save_dir``.
        if filename is not None and not is_safe_settings_filename(filename):
            await self.signal_operation_failed(
                f"Invalid agent-settings filename: {filename!r}"
            )
            return

        # Resolve target file. If the scene already has an overlay we write
        # into it; otherwise the caller MUST supply a filename so we know
        # what to create.
        if scene.agent_overrides is None:
            if not filename:
                await self.signal_operation_failed(
                    "No agent-settings file linked; filename is required"
                )
                return
            target_path = agent_settings_dir(scene.save_dir) / filename
            scene.agent_overrides = SceneAgentSettings(filepath=target_path)
            scene.agent_settings_file = filename
            scene._agent_settings_opted_out = False
        elif filename and filename != scene.agent_overrides.filename:
            # Caller wants to switch which file we write to. Move the in-memory
            # overlay's filepath; existing file (if any) at the new name is
            # treated as a fresh start — we overwrite below.
            target_path = agent_settings_dir(scene.save_dir) / filename
            scene.agent_overrides = SceneAgentSettings(
                filepath=target_path,
                agents=scene.agent_overrides.agents,
            )
            scene.agent_settings_file = filename

        scene.agent_overrides.replace_agent_overrides(agent_type, override or {})
        try:
            await scene.agent_overrides.write_to_file()
        except OSError as exc:
            log.warning(
                "scene-overrides write failed",
                agent_type=agent_type,
                filepath=str(scene.agent_overrides.filepath),
                error=str(exc),
            )
            await self.signal_operation_failed(
                f"Failed to write agent-settings file: {exc.strerror or exc}"
            )
            return

        # Re-emit agent + scene status so the frontend re-renders with the
        # newly-resolved values and the updated linked-file display.
        await agent.emit_status()
        # signal_operation_done triggers a scene auto-save when enabled, which
        # persists the `agent_settings_file` reference in the scene JSON so
        # the link survives reload.
        await self.signal_operation_done()
