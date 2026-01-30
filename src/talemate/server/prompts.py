"""
WebSocket handlers for prompt template management.

Provides API for frontend to manage template groups, templates,
and configure resolution priority.
"""

import pydantic
import structlog
from jinja2 import TemplateSyntaxError, Environment

from talemate.config import get_config
from talemate.prompts.groups import (
    GroupInfo,
    TemplateInfo,
    create_group,
    delete_group,
    delete_template,
    get_template_content,
    list_groups,
    list_templates,
    resolve_template,
    write_template,
    get_group_template_path,
)

from .websocket_plugin import Plugin

log = structlog.get_logger("talemate.server.prompts")


# --- Payload Models ---


class CreateGroupPayload(pydantic.BaseModel):
    name: str


class DeleteGroupPayload(pydantic.BaseModel):
    name: str
    force: bool = False


class SetGroupPriorityPayload(pydantic.BaseModel):
    priority: list[str]


class ListGroupTemplatesPayload(pydantic.BaseModel):
    group: str


class GetTemplatePayload(pydantic.BaseModel):
    uid: str
    group: str | None = None


class SaveTemplatePayload(pydantic.BaseModel):
    uid: str
    group: str
    content: str


class DeleteTemplatePayload(pydantic.BaseModel):
    uid: str
    group: str


class CreateTemplatePayload(pydantic.BaseModel):
    uid: str
    group: str
    content: str = ""


class SetTemplateSourcePayload(pydantic.BaseModel):
    uid: str
    group: str | None = None


# --- Helper Functions ---


def validate_jinja2_syntax(content: str) -> tuple[bool, list[str]]:
    """
    Validate Jinja2 template syntax.

    Returns:
        Tuple of (is_valid, list of error messages)
    """
    errors = []
    try:
        env = Environment()
        env.parse(content)
        return True, []
    except TemplateSyntaxError as e:
        errors.append(f"Line {e.lineno}: {e.message}")
        return False, errors


def parse_template_uid(uid: str) -> tuple[str, str]:
    """
    Parse a template UID into (agent, template_name).

    Args:
        uid: Template UID in format "{agent}.{template_name}"

    Returns:
        Tuple of (agent, template_name)

    Raises:
        ValueError: If UID format is invalid
    """
    if "." not in uid:
        raise ValueError(f"Invalid template UID format: {uid}")
    parts = uid.split(".", 1)
    return parts[0], parts[1]


# --- Plugin ---


class PromptsPlugin(Plugin):
    router = "prompts"

    # --- Group Management ---

    async def handle_list_groups(self, data: dict):
        """
        List all template groups.

        Request: {}
        Response: {
            "groups": [...],
            "scene_loaded": bool
        }
        """
        scene = self.scene if self.scene and self.scene.name else None
        groups = list_groups(scene)

        # Add is_scene flag to scene group if present
        groups_data = []
        for group in groups:
            group_dict = group.model_dump()
            if group.name == "scene":
                group_dict["is_scene"] = True
            groups_data.append(group_dict)

        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "list_groups",
                "data": {
                    "groups": groups_data,
                    "scene_loaded": scene is not None,
                },
            }
        )

    async def handle_create_group(self, data: dict):
        """
        Create a new template group.

        Request: {"name": "my-new-group"}
        Response: {"success": true, "group": {...}}
        """
        payload = CreateGroupPayload(**data)

        try:
            group = create_group(payload.name)
            self.websocket_handler.queue_put(
                {
                    "type": self.router,
                    "action": "create_group",
                    "data": {
                        "success": True,
                        "group": group.model_dump(),
                    },
                }
            )
        except ValueError as e:
            self.websocket_handler.queue_put(
                {
                    "type": self.router,
                    "action": "create_group",
                    "data": {
                        "success": False,
                        "error": str(e),
                    },
                }
            )

    async def handle_delete_group(self, data: dict):
        """
        Delete a template group.

        Request: {"name": "my-group", "force": true}
        Response: {"success": true}
        """
        payload = DeleteGroupPayload(**data)

        try:
            delete_group(payload.name, force=payload.force)

            # Also remove from group_priority if present
            config = get_config()
            if payload.name in config.prompts.group_priority:
                config.prompts.group_priority.remove(payload.name)
                await config.set_dirty()

            self.websocket_handler.queue_put(
                {
                    "type": self.router,
                    "action": "delete_group",
                    "data": {
                        "success": True,
                    },
                }
            )
        except (ValueError, FileNotFoundError) as e:
            self.websocket_handler.queue_put(
                {
                    "type": self.router,
                    "action": "delete_group",
                    "data": {
                        "success": False,
                        "error": str(e),
                    },
                }
            )

    # --- Group Activation & Priority ---

    async def handle_set_group_priority(self, data: dict):
        """
        Set the group priority order and activation state.

        Request: {
            "priority": ["user", "my-custom-group"],
        }
        Response: {"success": true}
        """
        payload = SetGroupPriorityPayload(**data)

        config = get_config()
        config.prompts.group_priority = payload.priority
        await config.set_dirty()

        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "set_group_priority",
                "data": {
                    "success": True,
                },
            }
        )

    # --- Template Listing ---

    async def handle_list_templates(self, data: dict):
        """
        List all templates with source information.

        Request: {}
        Response: {
            "templates": [...]
        }
        """
        scene = self.scene if self.scene and self.scene.name else None
        templates = list_templates(scene, include_sources=True)

        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "list_templates",
                "data": {
                    "templates": [t.model_dump() for t in templates],
                },
            }
        )

    async def handle_list_group_templates(self, data: dict):
        """
        List templates in a specific group.

        Request: {"group": "user"}
        Response: {
            "templates": [
                {"uid": "narrator.narrate-scene", "exists": true},
                ...
            ]
        }
        """
        payload = ListGroupTemplatesPayload(**data)
        scene = self.scene if self.scene and self.scene.name else None

        # Get all templates to know what UIDs exist
        all_templates = list_templates(scene, include_sources=True)

        # Build response with exists flag for each template
        templates_response = []
        for template in all_templates:
            exists = payload.group in template.available_in
            templates_response.append(
                {
                    "uid": template.uid,
                    "exists": exists,
                }
            )

        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "list_group_templates",
                "data": {
                    "group": payload.group,
                    "templates": templates_response,
                },
            }
        )

    # --- Template Content ---

    async def handle_get_template(self, data: dict):
        """
        Get template content.

        Request: {"uid": "narrator.narrate-scene", "group": "user"}
        Response: {"content": "...", "group": "user", "readonly": false}
        """
        payload = GetTemplatePayload(**data)

        try:
            agent, template_name = parse_template_uid(payload.uid)
        except ValueError as e:
            self.websocket_handler.queue_put(
                {
                    "type": self.router,
                    "action": "get_template",
                    "data": {
                        "error": str(e),
                    },
                }
            )
            return

        scene = self.scene if self.scene and self.scene.name else None

        if payload.group:
            # Get specific group's version
            content = get_template_content(
                payload.group, agent, template_name, scene
            )
            readonly = payload.group == "default"
            source_group = payload.group
        else:
            # Get resolved template (readonly)
            path, source_group = resolve_template(agent, template_name, scene)
            if path and path.exists():
                content = path.read_text(encoding="utf-8")
            else:
                content = None
            readonly = True

        if content is None:
            self.websocket_handler.queue_put(
                {
                    "type": self.router,
                    "action": "get_template",
                    "data": {
                        "error": f"Template not found: {payload.uid}",
                    },
                }
            )
            return

        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "get_template",
                "data": {
                    "uid": payload.uid,
                    "content": content,
                    "group": source_group,
                    "readonly": readonly,
                },
            }
        )

    async def handle_save_template(self, data: dict):
        """
        Save template content to a group.

        Request: {"uid": "narrator.narrate-scene", "group": "user", "content": "..."}
        Response: {
            "success": true,
            "syntax_valid": true,
            "syntax_errors": []
        }
        """
        payload = SaveTemplatePayload(**data)

        try:
            agent, template_name = parse_template_uid(payload.uid)
        except ValueError as e:
            self.websocket_handler.queue_put(
                {
                    "type": self.router,
                    "action": "save_template",
                    "data": {
                        "success": False,
                        "error": str(e),
                    },
                }
            )
            return

        # Validate syntax (but still save even if invalid)
        syntax_valid, syntax_errors = validate_jinja2_syntax(payload.content)

        scene = self.scene if self.scene and self.scene.name else None

        try:
            write_template(
                payload.group, agent, template_name, payload.content, scene
            )
            self.websocket_handler.queue_put(
                {
                    "type": self.router,
                    "action": "save_template",
                    "data": {
                        "success": True,
                        "syntax_valid": syntax_valid,
                        "syntax_errors": syntax_errors,
                    },
                }
            )
        except ValueError as e:
            self.websocket_handler.queue_put(
                {
                    "type": self.router,
                    "action": "save_template",
                    "data": {
                        "success": False,
                        "error": str(e),
                    },
                }
            )

    async def handle_delete_template(self, data: dict):
        """
        Delete template override from a group.

        Request: {"uid": "narrator.narrate-scene", "group": "user"}
        Response: {"success": true}
        """
        payload = DeleteTemplatePayload(**data)

        try:
            agent, template_name = parse_template_uid(payload.uid)
        except ValueError as e:
            self.websocket_handler.queue_put(
                {
                    "type": self.router,
                    "action": "delete_template",
                    "data": {
                        "success": False,
                        "error": str(e),
                    },
                }
            )
            return

        scene = self.scene if self.scene and self.scene.name else None

        try:
            deleted = delete_template(payload.group, agent, template_name, scene)
            self.websocket_handler.queue_put(
                {
                    "type": self.router,
                    "action": "delete_template",
                    "data": {
                        "success": deleted,
                        "error": None if deleted else "Template not found",
                    },
                }
            )
        except ValueError as e:
            self.websocket_handler.queue_put(
                {
                    "type": self.router,
                    "action": "delete_template",
                    "data": {
                        "success": False,
                        "error": str(e),
                    },
                }
            )

    async def handle_create_template(self, data: dict):
        """
        Create a new template file.

        Request: {"uid": "narrator.my-helper", "group": "user", "content": "..."}
        Response: {"success": true}
        """
        payload = CreateTemplatePayload(**data)

        try:
            agent, template_name = parse_template_uid(payload.uid)
        except ValueError as e:
            self.websocket_handler.queue_put(
                {
                    "type": self.router,
                    "action": "create_template",
                    "data": {
                        "success": False,
                        "error": str(e),
                    },
                }
            )
            return

        # Cannot create in default group
        if payload.group == "default":
            self.websocket_handler.queue_put(
                {
                    "type": self.router,
                    "action": "create_template",
                    "data": {
                        "success": False,
                        "error": "Cannot create templates in the default group",
                    },
                }
            )
            return

        # Check if template already exists in the target group
        scene = self.scene if self.scene and self.scene.name else None
        existing_content = get_template_content(
            payload.group, agent, template_name, scene
        )
        if existing_content is not None:
            self.websocket_handler.queue_put(
                {
                    "type": self.router,
                    "action": "create_template",
                    "data": {
                        "success": False,
                        "error": f"Template already exists: {payload.uid}",
                    },
                }
            )
            return

        try:
            write_template(
                payload.group, agent, template_name, payload.content, scene
            )
            self.websocket_handler.queue_put(
                {
                    "type": self.router,
                    "action": "create_template",
                    "data": {
                        "success": True,
                    },
                }
            )
        except ValueError as e:
            self.websocket_handler.queue_put(
                {
                    "type": self.router,
                    "action": "create_template",
                    "data": {
                        "success": False,
                        "error": str(e),
                    },
                }
            )

    # --- Per-Template Source Override ---

    async def handle_set_template_source(self, data: dict):
        """
        Set explicit source group for a template.

        Request: {"uid": "narrator.narrate-scene", "group": "my-custom"}
        Response: {"success": true}

        Pass group=null to remove override and use priority-based resolution.
        """
        payload = SetTemplateSourcePayload(**data)

        config = get_config()

        if payload.group is None:
            # Remove override
            if payload.uid in config.prompts.template_sources:
                del config.prompts.template_sources[payload.uid]
                await config.set_dirty()
        else:
            # Validate the template exists in the target group
            try:
                agent, template_name = parse_template_uid(payload.uid)
            except ValueError as e:
                self.websocket_handler.queue_put(
                    {
                        "type": self.router,
                        "action": "set_template_source",
                        "data": {
                            "success": False,
                            "error": str(e),
                        },
                    }
                )
                return

            scene = self.scene if self.scene and self.scene.name else None
            content = get_template_content(
                payload.group, agent, template_name, scene
            )

            if content is None:
                self.websocket_handler.queue_put(
                    {
                        "type": self.router,
                        "action": "set_template_source",
                        "data": {
                            "success": False,
                            "error": f"Template {payload.uid} not found in group {payload.group}",
                        },
                    }
                )
                return

            # Set override
            config.prompts.template_sources[payload.uid] = payload.group
            await config.set_dirty()

        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "set_template_source",
                "data": {
                    "success": True,
                },
            }
        )
