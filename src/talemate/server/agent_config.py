"""Websocket plugin for live agent-config mutations.

This plugin handles operations that mutate an agent's stored configuration
outside of the bulk ``configure_agents`` save path — primarily managing the
*dynamic-action registries* (e.g. TTS OpenAI-compatible backends): registering
a child action, unregistering it, renaming its label.

Each handler runs the canonical agent method (which fires lifecycle hooks),
saves the updated agent config to disk, and re-emits the agent status so the
frontend re-renders with the new section list.
"""

import copy

import structlog

from talemate.config import commit_config, get_config
from talemate.instance import AGENTS
from talemate.scene_agent_settings import (
    DEFAULT_SETTINGS_FILENAME,
    SceneAgentSettings,
    _safe_init_overlay,
    agent_settings_dir,
    is_safe_settings_filename,
)
from talemate.scene_agent_settings_patch import (
    SceneOverridePatchError,
    plan_scene_override_patch,
    apply_scene_override_plan,
)
from talemate.util import slugify

from .websocket_plugin import Plugin

log = structlog.get_logger("talemate.server.agent_config")


def strip_non_overridable_fields(agent, override: dict) -> list[str]:
    """Drop config values the agent declares as non-overridable from a sparse
    override dict (mutated in place) and return what was removed.

    Keys with no matching declaration are left alone — ``agent.actions`` only
    carries the dynamic children installed for the current config, so an
    unknown key is not proof that the field does not exist.
    """
    stripped = []
    for action_key, action_override in (override.get("actions") or {}).items():
        config_override = (action_override or {}).get("config") or {}
        if not config_override:
            continue
        action = agent.actions.get(action_key)
        declared = action.config or {} if action is not None else {}
        for config_key in list(config_override.keys()):
            field = declared.get(config_key)
            if field is not None and not field.scene_overridable:
                config_override.pop(config_key)
                stripped.append(f"{action_key}.{config_key}")
    return stripped


def _scene_identity(scene) -> str | None:
    """The loaded-scene generation a patch was composed for, when known."""
    if scene is None:
        return None
    scene_id = getattr(scene, "id", None)
    return str(scene_id) if scene_id else None


def _link_survives_reload(scene, filename: str) -> bool:
    """Whether ``filename`` is linked again when the stored scene file reloads:
    the file already linked, or a first link to the default file, which the
    load-time auto-link finds."""
    if scene.agent_overrides is not None:
        return filename == scene.agent_overrides.filename
    return filename == DEFAULT_SETTINGS_FILENAME and not scene._agent_settings_opted_out


class AgentConfigPlugin(Plugin):
    """Live mutations to an agent's stored configuration."""

    router = "agent_config"

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    async def _refuse(
        self, data: dict, message: str, extra: dict | None = None
    ) -> None:
        """Refuse a request, telling the sender which of its requests failed."""
        await self.signal_operation_failed(
            message,
            request_id=data.get("request_id"),
            failed_action=data.get("action"),
            extra=extra,
        )

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
            await self._refuse(data, msg)
            return None, None, None
        if not action_key or not agent.is_dynamic_registry(action_key):
            msg = f"'{action_key}' is not a dynamic registry on agent '{agent_type}'"
            log.warning(msg, action=data.get("action"))
            await self._refuse(data, msg)
            return None, None, None
        return agent, agent_type, action_key

    async def _persist_and_broadcast(self, agent, data: dict) -> None:
        # Concurrent writers of ``Config.agents``: this path, ``config/save``
        # (whole map) and the help agent's settings tools (background tasks,
        # not serialized by the dispatcher). Each writes in one synchronous
        # event-loop step, so no entry can tear; what a writer CAN do is ship a
        # map assembled before this op landed. The broadcast below is the
        # defense — it refreshes what those writers assemble from.
        await agent.save_config()
        # Holders of a config snapshot (the settings working copy, the stacking
        # base the drawer saves on) would otherwise still carry the pre-op
        # entry and undo this write on their next full-config save. Broadcast
        # before the status echo, so a frontend adopting the config sees it
        # first.
        await get_config().set_dirty()
        await commit_config()
        await agent.emit_status()
        await self.signal_operation_done(
            signal_only=True, request_id=data.get("request_id")
        )

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
            await self._refuse(data, "Label is required")
            return

        slug = slugify(label)
        if not slug:
            await self._refuse(data, f"Could not derive a slug from label '{label}'")
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
            await self._refuse(data, str(exc))
            return

        await agent.persist_dynamic_external_state(action_key)
        await self._persist_and_broadcast(agent, data)

    async def handle_unregister_child(self, data: dict):
        """Remove a child entry from a dynamic-action registry.

        Required: ``agent_type``, ``action_key``, ``slug``.
        """
        agent, _, action_key = await self._resolve_registry(data)
        if not agent:
            return

        slug = data.get("slug")
        if not slug:
            await self._refuse(data, "Slug is required")
            return

        agent.unregister_dynamic_child(action_key, slug)
        await agent.persist_dynamic_external_state(action_key)
        await self._persist_and_broadcast(agent, data)

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
            await self._refuse(data, "Slug is required")
            return
        if not label:
            await self._refuse(data, "Label is required")
            return

        agent.rename_dynamic_child_label(action_key, slug, label)
        await self._persist_and_broadcast(agent, data)

    # ------------------------------------------------------------------
    # Per-scene agent overrides
    # ------------------------------------------------------------------

    async def _refuse_scene_overrides(
        self, agent, data: dict, message: str, extra: dict | None = None
    ) -> None:
        """Reject an override save and put the frontend back on the truth.

        Senders (the settings view's override buffer, the agent panel's
        quick-toggle chips) update their local copy of the overlay
        optimistically, so a refusal that only raised an error toast would
        leave a value on screen that was never stored. Re-emitting agent status
        ships the unchanged overlay back.
        """
        if agent:
            await agent.emit_status()
        await self._refuse(data, message, extra=extra)

    async def handle_save_scene_overrides(self, data: dict):
        """Persist a sparse per-agent override set into the scene's
        agent-settings JSON file.

        Required: ``agent_type``, plus exactly one of ``override`` (replacement
        sparse AgentOverride dict) or ``patch`` (a sparse
        ``{set: {actions: ...}, clear: [{action, config?}]}`` merge).
        Optional: ``filename`` (creates / re-links the file when supplied;
        new links refuse existing names for replacements, while a first-link
        patch merges into an existing file), ``scene_identity`` (the
        scene generation the patch was composed for), ``request_id``.
        """
        agent_type = data.get("agent_type")
        override = data.get("override")
        patch = data.get("patch")
        filename = data.get("filename")

        if override is not None and patch is not None:
            await self._refuse(data, "Provide either 'override' or 'patch', not both")
            return

        agent = AGENTS.get(agent_type) if agent_type else None
        if not agent:
            await self._refuse(data, f"Agent '{agent_type}' not found")
            return

        # The sparse patch is validated as a whole before any live/link state is
        # touched: a malformed or unknown entry refuses the request instead of
        # applying the entries that came before it, and an invented action or
        # config never reaches disk.
        plan = None
        if patch is not None:
            try:
                plan = plan_scene_override_patch(agent, patch)
            except SceneOverridePatchError as exc:
                log.warning(
                    "scene-overrides patch refused",
                    agent_type=agent_type,
                    error=str(exc),
                )
                await self._refuse_scene_overrides(
                    agent, data, f"Invalid scene-override patch: {exc}"
                )
                return

        scene = getattr(agent, "scene", None)
        # A patch carries the scene generation it was composed for: refuse one
        # that crossed a scene load rather than write into the new scene.
        scene_identity = data.get("scene_identity")
        if (
            patch is not None
            and scene_identity is not None
            and scene_identity != _scene_identity(scene)
        ):
            log.warning(
                "scene-overrides patch refused: scene identity changed",
                agent_type=agent_type,
                sent=scene_identity,
                current=_scene_identity(scene),
            )
            await self._refuse_scene_overrides(
                agent, data, "The scene changed; the settings change was not saved."
            )
            return

        if scene is None:
            await self._refuse_scene_overrides(
                agent, data, f"Agent '{agent_type}' is not connected to a scene"
            )
            return

        if scene.agent_overrides is not None and scene.agent_overrides.pending:
            await self._refuse_scene_overrides(
                agent, data, "Scene creation is still in progress."
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
            # A scene can hold a live overlay and still have no filename — a
            # restore re-links the overlay from `project_name` and then clears
            # the filename — so this is not always a "not saved yet" scene.
            await self._refuse_scene_overrides(
                agent,
                data,
                "This scene has no save file, so its agent overrides cannot be "
                "changed. Save the scene first.",
            )
            return

        # Defense against path traversal — filename arrives over the wire
        # and must stay inside ``save_dir``.
        if filename is not None and not is_safe_settings_filename(filename):
            await self._refuse_scene_overrides(
                agent, data, f"Invalid agent-settings filename: {filename!r}"
            )
            return

        # the auto-save of a read-only scene never writes the link, so refuse
        # before any state change
        if (
            filename
            and scene.immutable_save
            and not _link_survives_reload(scene, filename)
        ):
            await self._refuse_scene_overrides(
                agent,
                data,
                f"This scene is read-only, so a link to {filename} would be lost "
                "on reload. Save the scene as a copy first.",
                extra={"save_as_required": True},
            )
            return

        target_path = (
            agent_settings_dir(scene.save_dir) / filename if filename else None
        )
        starts_file = target_path is not None and (
            (scene.agent_overrides is None and patch is None)
            or (
                scene.agent_overrides is not None
                and filename != scene.agent_overrides.filename
            )
        )
        if starts_file and target_path.exists():
            await self._refuse_scene_overrides(
                agent,
                data,
                f"Agent settings file {filename} already exists. Choose a new "
                "name, or link the existing file in World Editor → Scene → Settings.",
            )
            return

        # Everything below mutates in-memory state that agents resolve their
        # settings from; snapshot it so a failed write can be undone instead of
        # leaving the running scene on values that never reached disk. The
        # snapshot must be an independent copy: the patch mutates the live
        # slice in place, so a reference would be reinstalled already changed.
        previous_overlay = (
            copy.deepcopy(scene.agent_overrides)
            if scene.agent_overrides is not None
            else None
        )
        previous_settings_file = scene.agent_settings_file
        # Linking clears the opt-out; leaving it cleared after a failed write
        # would silently re-arm the load-time auto-link for a scene the user
        # opted out of.
        previous_opted_out = scene._agent_settings_opted_out

        def rollback() -> None:
            scene.agent_overrides = previous_overlay
            scene.agent_settings_file = previous_settings_file
            scene._agent_settings_opted_out = previous_opted_out

        # Resolve target file. If the scene already has an overlay we write
        # into it; otherwise the caller MUST supply a filename so we know
        # what to create. Linking a file is the only case that changes the
        # scene itself (it stores `agent_settings_file`), and so the only one
        # that needs the scene persisted afterwards.
        linked_file = False
        # A first link can load other agents' overrides out of an existing
        # file; those agents' effective settings change too.
        loaded_existing_overlay = False
        if scene.agent_overrides is None:
            if not filename:
                await self._refuse_scene_overrides(
                    agent, data, "No agent-settings file linked; filename is required"
                )
                return
            if patch is not None and target_path.exists():
                # A sparse hub patch merges, so an existing file's other agent
                # and action overrides have to be loaded first; a file that
                # cannot be read fails instead of being overwritten.
                if not await _safe_init_overlay(scene, target_path, filename):
                    rollback()
                    await self._refuse_scene_overrides(
                        agent,
                        data,
                        f"Failed to load agent settings file {filename}; "
                        "check the JSON is valid.",
                    )
                    return
                scene._agent_settings_opted_out = False
                linked_file = True
                loaded_existing_overlay = True
            else:
                scene.agent_overrides = SceneAgentSettings(filepath=target_path)
                scene.agent_settings_file = filename
                scene._agent_settings_opted_out = False
                linked_file = True
        elif filename and filename != scene.agent_overrides.filename:
            scene.agent_overrides = SceneAgentSettings(
                filepath=target_path,
                agents=scene.agent_overrides.agents,
            )
            scene.agent_settings_file = filename
            linked_file = True

        if plan is not None:
            stripped = apply_scene_override_plan(
                scene.agent_overrides, agent_type, plan
            )
        else:
            override = override or {}
            stripped = strip_non_overridable_fields(agent, override)
            scene.agent_overrides.replace_agent_overrides(agent_type, override)
        if stripped:
            log.warning(
                "scene-overrides save dropped non-overridable fields",
                agent_type=agent_type,
                fields=stripped,
            )
        undeclared = scene.agent_overrides.drop_undeclared_fields(
            agent_type, agent.actions
        )
        if undeclared:
            log.info(
                "scene-overrides save dropped undeclared fields",
                agent_type=agent_type,
                fields=undeclared,
            )

        try:
            await scene.agent_overrides.write_to_file()
        except OSError as exc:
            log.warning(
                "scene-overrides write failed",
                agent_type=agent_type,
                filepath=str(scene.agent_overrides.filepath),
                error=str(exc),
            )
            rollback()
            await self._refuse_scene_overrides(
                agent,
                data,
                f"Failed to write agent-settings file: {exc.strerror or exc}",
            )
            return

        # Re-emit agent + scene status so the frontend re-renders with the
        # newly-resolved values and the updated linked-file display. A first
        # link can have loaded other agents' overrides into the live scene, so
        # those agents report too — otherwise the hub keeps showing global
        # values and the wrong reset state.
        status_agents = [agent]
        if loaded_existing_overlay:
            for other_name in list(scene.agent_overrides.agents.keys()):
                other = AGENTS.get(other_name)
                if other is not None and other is not agent:
                    status_agents.append(other)
        for status_agent in status_agents:
            await status_agent.emit_status()
        # Effective knowledge eligibility is scene-derived, so an already-linked
        # overlay write must publish the scene status even though it does not
        # rewrite the scene file.
        scene.emit_status()
        # Overrides live in their own file, so the scene itself only needs
        # persisting when this save linked one: the auto-save writes the
        # `agent_settings_file` reference so the link survives reload. Repeat
        # saves (the settings page, the agents drawer, quick-toggle chip flips)
        # skip it — otherwise every chip click would rewrite the scene JSON or
        # mark it unsaved.
        await self.signal_operation_done(
            signal_only=not linked_file, request_id=data.get("request_id")
        )
