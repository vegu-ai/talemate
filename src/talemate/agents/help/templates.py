"""
World state template access for the help agent: reading, describing, creating
and patching every template type except themes, which keep their own tools in
``themes.py`` and are refused here.
"""

import enum
import os
import re
import types
import typing
from typing import TYPE_CHECKING, Any, Union

import pydantic

from talemate.scene_tools import SCENE_TOOL_ACTIONS
from talemate.world_state.templates.base import (
    MODELS,
    TEMPLATE_PATH_TALEMATE,
    Collection,
    Group,
    Template,
)

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = [
    "type_reference",
    "list_templates",
    "describe_template_type",
    "read_template",
    "create_template",
    "update_template",
]

# the same rules the Templates tab validates against, so a template created
# here can be edited and saved there afterwards
TEMPLATE_NAME_RE = re.compile(r"^[a-zA-Z0-9_ ]+$")
GROUP_NAME_INVALID_RE = re.compile(r'[<>:"/\\|?*]')

NEW_GROUP_AUTHOR = "Help chat"
NEW_GROUP_DESCRIPTION = "Templates created through the help chat."

THEME_TYPE = "theme"

THEME_REDIRECT = (
    "Themes have tools of their own, which know what each color slot paints and "
    "measure the contrast of what they write: list_themes, read_theme, "
    "create_theme, update_theme and apply_theme. Use those instead."
)

# what a type is for, one line each, for the prompt
TYPE_PURPOSE = {
    "character_attribute": "An attribute the AI writes for a character - personality, skills, anything a character has.",
    "character_detail": "A longer-form question about a character the AI answers to flesh out their backstory.",
    "spices": "A collection of instructions, one picked at random, that adds unexpectedness to a generation.",
    "writing_style": "A writing style handed to the AI, plus phrases to detect as unwanted in what it writes.",
    "state_reinforcement": "A question about a character or the world that is re-answered every few turns.",
    "scene_type": "A type of scene, with the rules and constraints that guide how it plays.",
    "scene_tool_shortcut": "A one-click entry in the scene tools: an agent action, a label, an icon and canned instructions.",
    "visual_style": "How image prompts are built - keyword or descriptive prompting, positive and negative.",
    "visual_finalizer": "Post-processing actions applied to an image prompt before it is generated.",
    "agent_persona": "How an agent presents itself in its prompts - tone, perspective, style.",
    THEME_TYPE: "The colors Talemate is painted with. " + THEME_REDIRECT,
}

TYPE_DOCS = {
    "character_attribute": "user-guide/templates/attribute.md",
    "character_detail": "user-guide/templates/detail.md",
    "spices": "user-guide/templates/spice.md",
    "writing_style": "user-guide/templates/writing-style.md",
    "state_reinforcement": "user-guide/templates/state.md",
    "scene_type": "user-guide/templates/scene_type.md",
    "scene_tool_shortcut": "user-guide/templates/scene-tool-shortcut.md",
    "visual_style": "user-guide/templates/index.md",
    "visual_finalizer": "user-guide/templates/visual-finalizer.md",
    "agent_persona": "user-guide/templates/index.md",
    THEME_TYPE: "user-guide/templates/themes.md",
}

# every template carries these; they are plumbing or belong to the Templates
# tab, so they are neither described nor writable here
HIDDEN_FIELDS = frozenset({"template_type", "group", "uid", "locked"})

# what a field is for, where the field name does not carry it. `instructions`
# means something different in every type, so it is always spelled out
FIELD_NOTES = {
    "character_attribute": {
        "attribute": "The attribute to write, e.g. 'Personality'. {character_name} and {player_name} are replaced when it is used.",
        "instructions": "Instructions to the AI writing the attribute's text.",
        "supports_spice": "Lets a spice collection be applied while this attribute is generated.",
        "supports_style": "Lets a writing style be applied while this attribute is generated.",
    },
    "character_detail": {
        "detail": "The question or statement about the character the AI answers, e.g. 'What is their greatest fear?'.",
        "instructions": "Instructions to the AI writing the detail's text.",
        "supports_spice": "Lets a spice collection be applied while this detail is generated.",
        "supports_style": "Lets a writing style be applied while this detail is generated.",
    },
    "spices": {
        "spices": "The spices, one of which is picked at random each time the collection applies.",
        "instructions": "The instruction the pick is rendered into. {spice} is replaced by the chosen entry.",
    },
    "writing_style": {
        "instructions": "The writing style handed to the AI as instructions.",
        "phrases": "Phrases to detect in what the AI writes, each with the instructions to fix it.",
    },
    "state_reinforcement": {
        "query": "The question, statement or attribute name that is tracked.",
        "state_type": "Who the state is tracked for.",
        "insert": "How the answer is attached to the context of later generations.",
        "interval": "How many turns pass between updates of the answer.",
        "auto_create": "Applies the template to a scene as it loads, without being asked.",
        "require_active": "Only update the state while the character is in the scene.",
        "instructions": "Extra instructions to the AI answering the query.",
    },
    "scene_type": {
        "description": "What this type of scene is. The AI reads it.",
        "instructions": "The rules and constraints that guide a scene of this type.",
    },
    "scene_tool_shortcut": {
        "action_id": "The scene tool action the shortcut runs.",
        "label": "What the entry is called in the scene tools menu.",
        "icon": "A Material Design Icon name, e.g. mdi-script-text.",
        "instructions": "The instructions the action runs with when the shortcut is clicked.",
    },
    "visual_style": {
        "positive_keywords": "Keywords added to the positive prompt under keyword prompting.",
        "negative_keywords": "Keywords added to the negative prompt under keyword prompting.",
        "positive_descriptive": "Text added to the positive prompt under descriptive prompting.",
        "negative_descriptive": "Text added to the negative prompt under descriptive prompting.",
        "visual_type": "Which of the visualizer's style slots this template fills. STYLE is the general art style.",
    },
    "visual_finalizer": {
        "finalizers": "The post-processing actions, applied to the prompt in order.",
    },
    "agent_persona": {
        "instructions": "The persona itself, handed to the agent in its prompts.",
        "initial_chat_message": "The director's opening message in a new or cleared director chat.",
        "initial_arc_chat_message": "The director's opening message in a director chat generating an arc.",
    },
}

COMMON_FIELD_NOTES = {
    "name": "Name of the template. Letters, digits, spaces and underscores only.",
    "priority": "Generation order among templates applied together: 1 low, 2 medium, 3 high.",
    "description": "What the template is for, shown in the Templates tab.",
    "favorite": "Marks the template with a star in the Templates tab.",
}

# fields the model types as a plain string while the valid values live
# somewhere else. Every other choice list is read off the model's own type
CHOICE_AUTHORITIES = {
    ("scene_tool_shortcut", "action_id"): lambda: [
        action.id for action in SCENE_TOOL_ACTIONS
    ],
}

AUTO_CREATE_REFUSED = (
    "Saving a state reinforcement template with auto_create on applies it to the "
    "characters of the loaded scene straight away, which writes the scene - and "
    "the scene is not yours to change. It applies on EVERY save, so a template "
    "that already carries auto_create cannot be changed here at all while a scene "
    "is loaded: re-applying it blanks the answers it has collected. Say that the "
    "change belongs in the Templates tab, or offer to make it with no scene "
    "loaded. Turning auto_create off is allowed."
)

# the state types `auto_apply_template_state_reinforcement` applies to; a
# `world` state reinforcement reaches no character, so it writes no scene
AUTO_APPLIED_STATE_TYPES = frozenset({"npc", "character", "player"})


# ---------------------------------------------------------------------------
# lookups and guards, shared with the theme tools
# ---------------------------------------------------------------------------


def template_collection(scene: "Scene") -> Collection:
    return scene.world_state_manager.template_collection


def find_group(templates: Collection, name: str) -> Group | None:
    name = (name or "").strip().lower()
    for group in templates.groups:
        if group.name.strip().lower() == name:
            return group
    return None


def is_shipped(group: Group) -> bool:
    if not group.path:
        return False
    shipped = os.path.realpath(TEMPLATE_PATH_TALEMATE)
    return os.path.realpath(group.path).startswith(shipped + os.sep)


def templates_dirty_conflict(templates_dirty: bool) -> str | None:
    """Refusal message while the Templates tab holds an unsaved template edit.

    The tab saves the template it is on as a whole - a field not yet left or an
    edit inside its save debounce all end in a save of the copy the tab holds,
    which predates anything written here.

    Best-effort by construction: the flag rides on the UX snapshot taken when
    the message was sent, so edits made while the agent is answering are not
    seen.
    """
    if not templates_dirty:
        return None
    return (
        "The Templates tab has an unsaved template edit - it saves the whole "
        "template it is on, which would overwrite this change. Ask the user to "
        "finish that edit (leave the field, close the editor) so it saves, then "
        "apply the change again."
    )


def invalid_group_name(name: str) -> str | None:
    if not name:
        return (
            "Name the template group this goes into. Existing groups are listed by "
            "list_templates; an unknown name creates the group."
        )
    if GROUP_NAME_INVALID_RE.search(name) or name.strip(". ") == "":
        return f"'{name}' is not a valid template group name."
    return None


def invalid_template_name(name: str) -> str | None:
    if not TEMPLATE_NAME_RE.fullmatch(name or ""):
        return (
            "A template name may only hold letters, digits, spaces and underscores, "
            f"got '{name}'."
        )
    return None


def template_id(template: Template) -> str:
    return f"{template.group}__{template.uid}"


# ---------------------------------------------------------------------------
# the field reference, rendered from the models
# ---------------------------------------------------------------------------


def _model(template_type: str) -> type[Template] | None:
    return MODELS.get(template_type)


def _choices(annotation) -> list | None:
    if typing.get_origin(annotation) is typing.Literal:
        return list(typing.get_args(annotation))
    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        return [member.value for member in annotation]
    return None


def _optional(annotation) -> tuple[Any, bool]:
    if typing.get_origin(annotation) in (Union, types.UnionType):
        args = [arg for arg in typing.get_args(annotation) if arg is not type(None)]
        if len(args) == 1:
            return args[0], True
    return annotation, False


def _nested_model(annotation) -> type[pydantic.BaseModel] | None:
    if isinstance(annotation, type) and issubclass(annotation, pydantic.BaseModel):
        return annotation
    return None


def _type_label(annotation) -> str:
    origin = typing.get_origin(annotation)

    if origin is list:
        args = typing.get_args(annotation)
        return f"list of {_type_label(args[0])}" if args else "list"
    if _choices(annotation):
        return "string"
    if _nested_model(annotation):
        return "object"
    if annotation in (str, int, float, bool):
        return {str: "string", int: "number", float: "number", bool: "boolean"}[
            annotation
        ]

    return str(annotation)


def _field_entry(
    template_type: str, field_name: str, field: pydantic.fields.FieldInfo
) -> dict:
    annotation, optional = _optional(field.annotation)
    entry: dict[str, Any] = {"type": _type_label(annotation)}

    if template_type:
        note = FIELD_NOTES.get(template_type, {}).get(
            field_name
        ) or COMMON_FIELD_NOTES.get(field_name)
        if note:
            entry["description"] = note

    if field.is_required():
        entry["required"] = True
    else:
        default = field.get_default(call_default_factory=True)
        entry["default"] = default.value if isinstance(default, enum.Enum) else default

    authority = CHOICE_AUTHORITIES.get((template_type, field_name))
    choices = authority() if authority else _choices(annotation)
    if choices:
        entry["choices"] = choices

    item_type = None
    if typing.get_origin(annotation) is list:
        args = typing.get_args(annotation)
        item_type = args[0] if args else None

    item_choices = _choices(item_type) if item_type is not None else None
    if item_choices:
        entry["item_choices"] = item_choices

    item_model = _nested_model(annotation) or (
        _nested_model(item_type) if item_type is not None else None
    )
    if item_model:
        # the notes are keyed on the template's own fields, and a nested model
        # reuses names the outer one has ('instructions'), so it takes none
        entry["object_fields"] = {
            name: _field_entry("", name, nested)
            for name, nested in item_model.model_fields.items()
        }

    if optional:
        entry["nullable"] = True

    return entry


def _field_reference(template_type: str) -> dict:
    model = _model(template_type)
    return {
        name: _field_entry(template_type, name, field)
        for name, field in model.model_fields.items()
        if name not in HIDDEN_FIELDS
    }


def type_reference() -> list[dict]:
    """The types these tools write, and what each one is for, for the prompt.

    Themes are left out: the prompt renders this as the valid values of
    `template_type`, and every tool that takes one refuses a theme. An
    unfiltered `list_templates` still shows the themes that exist.
    """
    return [
        {"type": template_type, "purpose": TYPE_PURPOSE[template_type]}
        for template_type in sorted(MODELS)
        if template_type in TYPE_PURPOSE and template_type != THEME_TYPE
    ]


def _unknown_type(template_type: str) -> str:
    known = ", ".join(entry["type"] for entry in type_reference())
    return f"Unknown template type '{template_type}'. Valid types: {known}."


def _type_conflict(template_type: str) -> str | None:
    if template_type == THEME_TYPE:
        return THEME_REDIRECT
    if template_type not in MODELS or template_type not in TYPE_PURPOSE:
        return _unknown_type(template_type)
    return None


# ---------------------------------------------------------------------------
# payloads
# ---------------------------------------------------------------------------


def _entry(group: Group, template: Template) -> dict:
    entry: dict[str, Any] = {
        "id": template_id(template),
        "name": template.name,
        "template_type": template.template_type,
        "group": group.name,
    }
    description = getattr(template, "description", None)
    if description:
        entry["description"] = description
    if template.locked:
        entry["locked"] = "shipped with Talemate - cannot be edited or deleted"
    if template.favorite:
        entry["favorite"] = True
    return entry


def _templates(
    templates: Collection, template_type: str | None = None
) -> list[tuple[Group, Template]]:
    return [
        (group, template)
        for group in templates.groups
        for template in group.templates.values()
        if not template_type or template.template_type == template_type
    ]


def _resolve(templates: Collection, ref: str) -> tuple[Group, Template]:
    """Resolve a template id (``group__uid``) or template name to its template."""
    ref = (ref or "").strip()
    known = _templates(templates)

    if not ref:
        raise ValueError("Provide the id or the name of a template.")

    for group, template in known:
        if template_id(template) == ref:
            return group, template

    matches = [
        (group, template)
        for group, template in known
        if template.name.strip().lower() == ref.lower()
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        ids = ", ".join(template_id(template) for _group, template in matches)
        raise ValueError(
            f"Several templates are named '{ref}'. Use the id of the one you mean: {ids}"
        )

    raise ValueError(
        f"No template '{ref}'. list_templates gives the id of every template."
    )


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------


def list_templates(
    scene: "Scene", template_type: str | None = None
) -> list[dict] | str:
    """List the templates, optionally only those of one type."""
    if template_type:
        conflict = _type_conflict(template_type)
        if conflict:
            return conflict

    found = _templates(template_collection(scene), template_type)

    if not found:
        of_type = f" of type '{template_type}'" if template_type else ""
        return f"No templates{of_type} exist yet."

    return [_entry(group, template) for group, template in found]


def describe_template_type(template_type: str) -> dict | str:
    """The fields a template type carries, with their types and valid values."""
    conflict = _type_conflict(template_type)
    if conflict:
        return conflict

    payload = {
        "template_type": template_type,
        "purpose": TYPE_PURPOSE[template_type],
        "documentation": TYPE_DOCS[template_type],
        "fields": _field_reference(template_type),
    }

    if template_type == "state_reinforcement":
        payload["auto_create_note"] = AUTO_CREATE_REFUSED

    return payload


def read_template(scene: "Scene", template_id_or_name: str) -> dict | str:
    """Return one template with every field it carries."""
    try:
        group, template = _resolve(template_collection(scene), template_id_or_name)
    except ValueError as exc:
        return str(exc)

    if template.template_type == THEME_TYPE:
        return THEME_REDIRECT

    payload = _entry(group, template)
    payload["fields"] = {
        name: value
        for name, value in template.model_dump().items()
        if name not in HIDDEN_FIELDS
    }
    return payload


# ---------------------------------------------------------------------------
# writes
# ---------------------------------------------------------------------------


def _reject_unknown_fields(template_type: str, fields: dict) -> str | None:
    valid = _field_reference(template_type)
    unknown = [name for name in fields if name not in valid]
    if not unknown:
        return None
    return (
        f"'{', '.join(unknown)}' is not a field of a {template_type} template. Valid "
        f"fields: {', '.join(valid)}. describe_template_type gives them with their "
        "types and valid values."
    )


def _reject_unknown_choices(template_type: str, fields: dict) -> str | None:
    for (owner, field_name), authority in CHOICE_AUTHORITIES.items():
        if owner != template_type or field_name not in fields:
            continue
        choices = authority()
        if fields[field_name] not in choices:
            return (
                f"'{fields[field_name]}' is not a valid {field_name}. Valid values: "
                f"{', '.join(str(choice) for choice in choices)}."
            )
    return None


def _auto_create_conflict(
    scene_loaded: bool, template_type: str, data: dict
) -> str | None:
    """Refusal when the save this call would make applies to the loaded scene.

    ``data`` is the template as it would be saved, not the fields the call
    named: `save_template` applies any template whose `auto_create` is set, so
    a patch to an unrelated field of one that already carries it re-applies it -
    and a re-apply writes an empty answer over everything it had collected.
    """
    if template_type != "state_reinforcement" or not scene_loaded:
        return None
    if not data.get("auto_create"):
        return None
    if data.get("state_type") not in AUTO_APPLIED_STATE_TYPES:
        return None
    return AUTO_CREATE_REFUSED


def _name_taken(
    group: Group, template_type: str, name: str, keep: Template | None = None
) -> str | None:
    for sibling in group.templates.values():
        if sibling is keep or sibling.template_type != template_type:
            continue
        if sibling.name.strip().lower() != name.strip().lower():
            continue
        return (
            f"Group '{group.name}' already holds a {template_type} template called "
            f"'{sibling.name}'. Update that one, or pick another name."
        )
    return None


def _locked_conflict(template: Template) -> str | None:
    if not template.locked:
        return None
    return (
        f"'{template.name}' ships with Talemate and cannot be edited. Offer to copy it "
        "into a group of the user's own instead - read_template gives its fields, "
        "create_template writes them into a group of theirs."
    )


def _validated(template_type: str, data: dict) -> Template:
    try:
        return MODELS[template_type].model_validate(data)
    except pydantic.ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first["loc"])
        raise ValueError(f"Invalid value for '{location}': {first.get('msg')}")


async def create_template(
    scene: "Scene",
    template_type: str,
    name: str,
    group: str,
    fields: dict | None = None,
    templates_dirty: bool = False,
    *,
    scene_loaded: bool,
) -> dict | str:
    """Create a template of ``template_type`` in the named group."""
    conflict = templates_dirty_conflict(templates_dirty) or _type_conflict(
        template_type
    )
    if conflict:
        return conflict

    name = (name or "").strip()
    invalid = invalid_template_name(name)
    if invalid:
        return invalid

    group_name = (group or "").strip()
    invalid = invalid_group_name(group_name)
    if invalid:
        return invalid

    fields = fields or {}
    if not isinstance(fields, dict):
        return (
            "'fields' must map field names to values, e.g. "
            "{'attribute': 'Personality', 'instructions': 'Keep it to one paragraph.'}."
        )

    if "name" in fields:
        return "Pass the template's name as the 'name' argument, not inside 'fields'."

    refusal = _reject_unknown_fields(template_type, fields) or _reject_unknown_choices(
        template_type, fields
    )
    if refusal:
        return refusal

    try:
        template = _validated(
            template_type, {**fields, "name": name, "template_type": template_type}
        )
    except ValueError as exc:
        return str(exc)

    refusal = _auto_create_conflict(scene_loaded, template_type, template.model_dump())
    if refusal:
        return refusal

    templates = template_collection(scene)
    target = find_group(templates, group_name)

    if target and is_shipped(target):
        return (
            f"'{target.name}' is a group that ships with Talemate and does not take "
            "new templates. Name a group of the user's own instead - an unknown name "
            "creates it."
        )
    if target:
        taken = _name_taken(target, template_type, name)
        if taken:
            return taken

    manager = scene.world_state_manager
    created_group = False
    if not target:
        target = Group(
            author=NEW_GROUP_AUTHOR,
            name=group_name,
            description=NEW_GROUP_DESCRIPTION,
        )
        try:
            await manager.save_template_group(target)
        except ValueError as exc:
            return str(exc)
        created_group = True

    template.group = target.uid
    await manager.save_template(template)

    return {
        "created": True,
        "template_id": template_id(template),
        "name": template.name,
        "template_type": template_type,
        "group": target.name,
        "group_created": created_group,
        "fields": sorted(fields),
    }


async def update_template(
    scene: "Scene",
    template_id_or_name: str,
    fields: dict,
    templates_dirty: bool = False,
    *,
    scene_loaded: bool,
) -> dict | str:
    """Change the named fields of an existing template, leaving the rest alone."""
    conflict = templates_dirty_conflict(templates_dirty)
    if conflict:
        return conflict

    templates = template_collection(scene)
    try:
        group, template = _resolve(templates, template_id_or_name)
    except ValueError as exc:
        return str(exc)

    template_type = template.template_type
    conflict = _type_conflict(template_type) or _locked_conflict(template)
    if conflict:
        return conflict

    if is_shipped(group):
        return (
            f"'{template.name}' lives in '{group.name}', a group that ships with "
            "Talemate. Copy it into a group of the user's own with create_template "
            "and change the copy."
        )

    if not isinstance(fields, dict) or not fields:
        return "Name the fields to change, e.g. {'instructions': 'Keep it short.'}."

    refusal = _reject_unknown_fields(template_type, fields) or _reject_unknown_choices(
        template_type, fields
    )
    if refusal:
        return refusal

    if "name" in fields:
        new_name = str(fields["name"]).strip()
        invalid = invalid_template_name(new_name) or _name_taken(
            group, template_type, new_name, keep=template
        )
        if invalid:
            return invalid

    data = template.model_dump()
    changes = {}
    for field_name, value in fields.items():
        if data[field_name] == value:
            continue
        changes[field_name] = {"previous": data[field_name], "new": value}
        data[field_name] = value

    if not changes:
        return f"'{template.name}' already holds those values - nothing was changed."

    try:
        patched = _validated(template_type, data)
    except ValueError as exc:
        return str(exc)

    refusal = _auto_create_conflict(scene_loaded, template_type, patched.model_dump())
    if refusal:
        return refusal

    await scene.world_state_manager.save_template(patched)

    return {
        "updated": True,
        "template_id": template_id(patched),
        "name": patched.name,
        "template_type": template_type,
        "group": group.name,
        "changes": changes,
    }
