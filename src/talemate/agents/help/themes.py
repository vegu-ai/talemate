"""
Theme template access for the help agent.

Exposes the theme world state templates to the LLM through focal callbacks:
listing and reading themes, creating one, patching the slots of an existing
one and activating it. Colors, message styling, the light/dark mode and the
code editor scheme are all reachable; nothing else about a template is.

Writes mirror the frontend save paths - they go through ``WorldStateManager``,
so a locked template stays locked, the resolved-theme cache is dropped and the
group file is written the same way the Templates tab writes it. Shipped
templates (and the directory they live in) are read-only here: a user theme
belongs in a group of the user's own.
"""

import math
import uuid
from typing import TYPE_CHECKING, Any

import pydantic

from talemate.agents.help.templates import (
    GROUP_NAME_INVALID_RE,
    NEW_GROUP_AUTHOR,
    NEW_GROUP_DESCRIPTION,
    TEMPLATE_NAME_RE,
    find_group,
    is_shipped,
    template_collection,
    templates_dirty_conflict,
)
from talemate.config import get_config
from talemate.util.colors import contrast_ratio, describe_color
from talemate.world_state.templates.base import (
    Collection,
    Group,
)
from talemate.world_state.templates.theme import (
    CODE_EDITOR_THEMES,
    AppColors,
    ChatColors,
    MessageColors,
    SurfaceColors,
    Theme,
    ThemeAppearance,
)

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = [
    "slot_reference",
    "analyze_theme",
    "list_themes",
    "read_theme",
    "create_theme",
    "update_theme",
    "apply_theme",
]

COLOR_GROUPS = {
    "surfaces": SurfaceColors,
    "app": AppColors,
    "messages": MessageColors,
    "chats": ChatColors,
}

# the active theme's colors, mode and code editor scheme are resolved live on
# every render, but its message styling is not - the app reads that from the
# appearance config, which only a theme apply (or the Restore from theme button)
# writes
STYLING_NOT_LIVE = (
    "The colors of the active theme repaint the app as they are written, but "
    "message styling does not: the app reads styling from the appearance "
    "settings, which a theme writes only when it is applied. This change is "
    "saved in the theme and shows once the theme is applied again (apply_theme, "
    "which replaces ALL of the user's message styling with the theme's), or when "
    "the user clicks 'Restore from theme' on the Appearance > Messages page. Say "
    "so instead of reporting a change the user can see."
)


# What each slot actually paints, read off the frontend rather than off the
# slot names. The uses after the semicolon are the ones a name does not
# suggest: a palette that ignores them looks accidental in half the app.
SLOT_PAINTS = {
    "surfaces.background": "The page behind everything, including the scene message area messages are read on.",
    "surfaces.surface": "Cards, dialogs, drawers and toolbars; the translucent message panel over a scene backdrop.",
    "surfaces.surface_bright": "The bright surface step Vuetify draws for raised areas.",
    "surfaces.surface_light": "The lighter surface step - nested cards, import panels, secondary toolbars.",
    "surfaces.surface_variant": "The fill behind every tooltip in the app, with on_surface_variant as the label drawn on it. Vuetify's chip half of the token is unused here - Talemate draws its own chips tonal, text or outlined - and one outlined alert in the world editor also takes it.",
    "surfaces.on_surface_variant": "The text drawn on surface_variant, so it has to contrast with it.",
    "app.primary": "The main accent: buttons, active tabs, focus rings, selected rows, and 64 spans of literal text. The most used color in the app.",
    "app.secondary": "The second accent, for background activity; also the theme template chip.",
    "app.delete": "Destructive actions - remove buttons and delete confirmations.",
    "app.cancel": "Cancel, close and reset buttons.",
    "app.muted": "De-emphasized text and icons throughout. The second most used color in the app.",
    "app.mutedheader": "Captions and small headers above muted text; message toolbar chips; every markdown heading, table header and code span, the last of these drawn on the mutedbg fill.",
    "app.mutedbg": "Filled bands drawn under content: panel section headers and library toolbars, the director message's left rule, and the fill behind markdown code spans and code blocks (whose text is mutedheader).",
    "app.normal": "Body text in the message edit box. Character message text takes the character's own color instead.",
    "app.unsaved": "The 'not saved yet' marker on new characters and loaded presets.",
    "app.favorite": "The favorite star on templates.",
    "app.dirty": "The 'edited, not saved yet' tint on template and settings fields; the Revise chip on a message.",
    "app.persona": "Agent persona templates and the director console persona chip; also the character and card icons in the scene browser.",
    "app.highlight1": "Character attribute templates; also the 'editing' chip on a message, client warning icons, character badges.",
    "app.highlight2": "Character detail templates; also the reasoning token and effort sliders in the client list, the Minor/Major/Curveball buttons in the narrator tools, the creative-mode pulse in the scene tools, the timeline's scene name chip.",
    "app.highlight3": "State reinforcement templates; also the node editor's save-nodes action and enabled agent settings chips.",
    "app.highlight4": "Spice collection templates; also the spice-applied notice and character suggestion alerts.",
    "app.highlight5": "Writing style, visual style and visual finalizer templates; also every scene tool hint chip, agent status chips and suggestion markers.",
    "app.highlight6": "Scene type templates; also everything shared-world (shared attributes and details, the world share icons and cards) and the save button once the scene needs saving.",
    "app.highlight7": "Scene tool shortcut templates; also the client actions button and the save rows in the scene browser.",
    "app.inactive": "The deleted line of a diff in the agent messages, paired with success for the inserted line - so it wants to read as a removal, not as a disabled control. Named inactive because Vuetify owns text-disabled.",
    "app.module_selected": "The border of the selected module tile in the node editor library.",
    "app.module_locked_selected": "The border of a selected locked module tile in the node editor library.",
    "app.success": "Success status: toasts, alerts, chips, enabled markers.",
    "app.info": "Informational status: toasts, alerts, notes.",
    "app.warning": "Warning status: toasts, alerts, and the 'changed elsewhere' markers.",
    "app.error": "Error status: failed generations, invalid fields, error alerts.",
    "messages.narrator": "Narrator message text.",
    "messages.actor": "Character dialogue text; also the user's own bubbles in the director chat and the help chat.",
    "messages.director": "Director instruction message text and the director console heading.",
    "messages.time": "Time passage message text and its chips.",
    "messages.context_investigation": "Context investigation message text.",
    "messages.information": "Information message text; also timeline rebase notes.",
    "messages.quotes": "Quoted speech inside message text, while quotes carry their own color.",
    "messages.parentheses": "Parenthesized text inside messages, while parentheses carry their own color.",
    "messages.brackets": "Bracketed text inside messages, while brackets carry their own color.",
    "messages.emphasis": "Emphasized (*starred*) text inside messages, while emphasis carries its own color.",
    "messages.entities": "Highlighted entity names inside messages, while entities carry their own color.",
    "messages.play_audio": "The play-audio marker on a spoken message and the audio button in the scene tools.",
    "messages.border": "Avatar, message image and config table borders and dividers - decorative except for the scene timeline slider's track, which is an interface component.",
    "messages.defaultBadge": "The badge and outline marking the current visual asset in the asset grid.",
    "chats.dchat_msg_director": "Director chat bubbles from the director: a tonal fill of this color with its text drawn in it.",
    "chats.dchat_msg_action_result": "Director chat bubbles reporting an action result.",
    "chats.dchat_msg_compaction": "The tonal tint of the card carrying a compaction notice. The notice text itself is drawn in muted, so this slot paints no text.",
    "chats.hchat_msg_help": "Help chat bubbles from the help agent (this chat).",
    "chats.hchat_msg_doc_result": "Help chat bubbles carrying a documentation or tool result.",
}

# WCAG asks 4.5:1 of normal text and 3:1 of a user interface component. Which
# one a slot answers to is decided by the most demanding thing it paints: an
# accent that also sets 64 `text-primary` spans is text, whatever else it
# tints.
TEXT_SLOTS = frozenset(
    {
        "surfaces.on_surface_variant",
        "app.primary",
        "app.secondary",
        "app.delete",
        "app.cancel",
        "app.mutedheader",
        "app.normal",
        "app.inactive",
        "app.success",
        "app.info",
        "app.warning",
        "app.error",
        "app.unsaved",
        "app.highlight3",
        "app.highlight4",
        "app.highlight5",
        "app.highlight6",
        "messages.narrator",
        "messages.actor",
        "messages.director",
        "messages.time",
        "messages.context_investigation",
        "messages.information",
        "messages.quotes",
        "messages.parentheses",
        "messages.brackets",
        "messages.emphasis",
        "messages.entities",
    }
)

# What a slot is drawn ON is a property of the markup, not of the theme, and
# nothing here can see markup. Two grounds are modelled - the page and the card
# - and the one that was measured is always named. These slots are drawn
# somewhere else, so they get no number at all: a ratio against a pairing that
# never renders reads as reassurance, which is worse than saying nothing.
UNMEASURED_GROUNDS = {
    "app.muted": (
        "several wrappers dim it by opacity before any color is chosen "
        "(plugins/vuetify.js documents this), so what renders is not this color"
    ),
    "app.mutedheader": (
        "markdown code spans and blocks draw it on the mutedbg fill "
        "(DirectorConsoleChatMessageMarkdown.vue), not on the page or a card"
    ),
    "app.mutedbg": (
        "it is a fill drawn under content; what needs measuring is the text on "
        "it, which is mutedheader"
    ),
    "messages.border": (
        "mostly decorative (borders, dividers), but it is also the timeline "
        "slider's track, which is an interface component and owes 3:1"
    ),
    "messages.defaultBadge": (
        "the badge fills with it and hard-codes a white label "
        "(VisualAssetBadge.vue), so the pair that matters is white on this color"
    ),
    "chats.dchat_msg_director": None,
    "chats.dchat_msg_action_result": None,
    "chats.dchat_msg_compaction": (
        "the compaction notice draws its text in `muted`, so this slot only "
        "paints the card's tonal tint"
    ),
    "chats.hchat_msg_help": None,
    "chats.hchat_msg_doc_result": None,
}

TONAL_BUBBLE = (
    "chat bubbles fill tonally with this color and draw their text in it too "
    "(Vuetify's tonal variant), so the ground is the surface pulled toward the "
    "text rather than the surface"
)

for _slot, _reason in UNMEASURED_GROUNDS.items():
    if _reason is None:
        UNMEASURED_GROUNDS[_slot] = TONAL_BUBBLE

TEXT_REFERENCE = 4.5
UI_REFERENCE = 3.0

# The fills the interface draws content on, each of them a theme slot. Every
# slot is drawn on the page or on a card; only some are also drawn on a toolbar
# band, so the band is a per-slot ground rather than a group-wide one - handing
# it to the whole app group reports colors against a fill they never touch.
GROUP_GROUNDS = {
    "app": ("background", "surface"),
    "messages": ("background", "surface"),
}

# Surveyed from the frontend: every `color="mutedbg"` container, the colors
# drawn inside it, and the colors the components rendered inside it draw with -
# `cancel` reaches a band only that way, through ConfirmActionInline inside the
# direction timeline's toolbar. `variant="text"` controls in these bands have no
# fill of their own, so their labels are text on the band.
BAND_SLOTS = frozenset(
    {
        "app.cancel",
        "app.delete",
        "app.error",
        "app.highlight3",
        "app.highlight6",
        "app.info",
        "app.muted",
        "app.mutedheader",
        "app.primary",
        "app.secondary",
        "app.success",
        "app.warning",
    }
)

CONTRAST_NOTE = (
    "Ratios are WCAG 2.x between two colors of this theme, truncated down to "
    "two decimals. `measured_against` names which of the theme's own fills "
    "produced the number - the page (background), a card or drawer (surface), "
    "or a toolbar band (mutedbg), which only the slots the interface actually "
    "puts on one are measured against - and the worst of the fills a slot is "
    "drawn on is the one reported. Grounds outside the palette are NOT modelled: "
    "a tonal fill tints itself with the text color, and several wrappers dim by "
    "opacity before a color is chosen. Slots drawn that way are under "
    "`unmeasured` with the reason and carry no number - treat those as unknown, "
    "not as fine. `wcag_reference` is what WCAG asks of what that slot paints; "
    "nothing here decides whether a slot passes."
)


def slot_reference() -> dict:
    """The slots a theme carries and what each one paints, for the prompt.

    The names are rendered from the models rather than written out by hand, so
    what the LLM is given cannot drift from what the write path validates
    against. The descriptions are static, so they belong in the prompt (which
    is cached) rather than in every tool result.
    """
    return {
        "colors": {
            key: {
                slot: SLOT_PAINTS.get(f"{key}.{slot}", "")
                for slot in model.model_fields
            }
            for key, model in COLOR_GROUPS.items()
        },
        "appearance": list(ThemeAppearance.model_fields),
    }


# ---------------------------------------------------------------------------
# lookup helpers
# ---------------------------------------------------------------------------


def _themes(collection: Collection) -> list[tuple[Group, Theme]]:
    return [
        (group, template)
        for group in collection.groups
        for template in group.templates.values()
        if isinstance(template, Theme)
    ]


def _theme_id(template: Theme) -> str:
    return f"{template.group}__{template.uid}"


def _resolve_theme(collection: Collection, ref: str) -> tuple[Group, Theme]:
    """Resolve a theme id (``group__uid``) or theme name to its template."""
    ref = (ref or "").strip()
    themes = _themes(collection)

    if not ref:
        raise ValueError("Provide the id or the name of a theme.")

    for group, template in themes:
        if _theme_id(template) == ref:
            return group, template

    matches = [
        (group, template)
        for group, template in themes
        if template.name.strip().lower() == ref.lower()
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        ids = ", ".join(_theme_id(template) for _group, template in matches)
        raise ValueError(
            f"Several themes are named '{ref}'. Use the id of the one you mean: {ids}"
        )

    known = ", ".join(
        f"{template.name} ({_theme_id(template)})" for _g, template in themes
    )
    raise ValueError(f"No theme '{ref}'. Known themes: {known or '(none)'}")


# ---------------------------------------------------------------------------
# payloads
# ---------------------------------------------------------------------------


def _theme_entry(group: Group, template: Theme, active_theme_id: str | None) -> dict:
    entry: dict[str, Any] = {
        "id": _theme_id(template),
        "name": template.name,
        "group": group.name,
        "mode": "dark" if template.dark else "light",
        "active": _theme_id(template) == active_theme_id,
    }
    if template.locked:
        entry["locked"] = "shipped with Talemate - cannot be edited or deleted"
    if template.favorite:
        entry["favorite"] = True
    if template.instructions:
        entry["notes"] = template.instructions
    return entry


# ---------------------------------------------------------------------------
# guards
# ---------------------------------------------------------------------------


def _app_settings_dirty_conflict(app_settings_dirty: bool) -> str | None:
    if not app_settings_dirty:
        return None
    return (
        "The application settings view has unsaved edits - applying a theme writes "
        "the appearance settings, so saving them afterwards would overwrite it. Ask "
        "the user to save or discard their settings changes first."
    )


def _locked_conflict(template: Theme) -> str | None:
    if not template.locked:
        return None
    return (
        f"'{template.name}' ships with Talemate and cannot be edited. Offer to copy it "
        f"into a group of the user's own instead - create_theme with base_theme "
        f"'{_theme_id(template)}' takes all of its colors as the starting point."
    )


# ---------------------------------------------------------------------------
# patching
# ---------------------------------------------------------------------------


def _merge_colors(data: dict, colors: dict, changes: dict):
    if not isinstance(colors, dict):
        raise ValueError(
            "'colors' must be grouped by area, e.g. "
            "{'surfaces': {'background': '#002B36'}, 'app': {'primary': '#268BD2'}}."
        )

    for group_key, slots in colors.items():
        model = COLOR_GROUPS.get(group_key)
        if not model:
            raise ValueError(
                f"Unknown color group '{group_key}'. Valid groups: "
                f"{', '.join(COLOR_GROUPS)}."
            )
        if not isinstance(slots, dict):
            raise ValueError(
                f"'colors.{group_key}' must map slot names to colors, got {slots!r}."
            )
        for slot, color in slots.items():
            if slot not in model.model_fields:
                raise ValueError(
                    f"Unknown slot '{slot}' in color group '{group_key}'. Valid slots: "
                    f"{', '.join(model.model_fields)}."
                )
            previous = data[group_key][slot]
            if previous == color:
                continue
            data[group_key][slot] = color
            changes[f"colors.{group_key}.{slot}"] = {
                "previous": previous,
                "new": color,
            }


def _merge_appearance(data: dict, appearance: dict, changes: dict):
    if not isinstance(appearance, dict):
        raise ValueError(
            "'appearance' must map message or markup types to their style flags, e.g. "
            "{'narrator': {'italic': true}}."
        )

    for key, value in appearance.items():
        if key not in ThemeAppearance.model_fields:
            raise ValueError(
                f"Unknown appearance key '{key}'. Valid keys: "
                f"{', '.join(ThemeAppearance.model_fields)}."
            )
        if not isinstance(data[key], dict):
            if data[key] == value:
                continue
            changes[f"appearance.{key}"] = {"previous": data[key], "new": value}
            data[key] = value
            continue
        if not isinstance(value, dict):
            raise ValueError(
                f"'appearance.{key}' holds style flags "
                f"({', '.join(data[key])}), got {value!r}."
            )
        for flag, flag_value in value.items():
            if flag not in data[key]:
                raise ValueError(
                    f"'{key}' has no style flag '{flag}'. Valid flags: "
                    f"{', '.join(data[key])}."
                )
            if data[key][flag] == flag_value:
                continue
            changes[f"appearance.{key}.{flag}"] = {
                "previous": data[key][flag],
                "new": flag_value,
            }
            data[key][flag] = flag_value


def _patched(
    template: Theme,
    colors: dict | None,
    appearance: dict | None,
    dark: bool | None,
    code_editor: str | None,
) -> tuple[Theme, dict]:
    """Return a copy of ``template`` with the supplied values merged in.

    The patched data is re-validated through the model, so a malformed color or
    an unknown code editor scheme is rejected here rather than written.
    """
    data = template.model_dump()
    changes: dict[str, dict] = {}

    if colors:
        _merge_colors(data["colors"], colors, changes)
    if appearance:
        _merge_appearance(data["appearance"], appearance, changes)
    if dark is not None and dark != data["dark"]:
        changes["dark"] = {"previous": data["dark"], "new": dark}
        data["dark"] = dark
    if code_editor and code_editor != data["code_editor"]:
        if code_editor not in CODE_EDITOR_THEMES:
            raise ValueError(
                f"Unknown code editor scheme '{code_editor}'. Valid schemes: "
                f"{', '.join(CODE_EDITOR_THEMES)}."
            )
        changes["code_editor"] = {
            "previous": data["code_editor"],
            "new": code_editor,
        }
        data["code_editor"] = code_editor

    try:
        return Theme.model_validate(data), changes
    except pydantic.ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first["loc"])
        raise ValueError(f"Invalid value for '{location}': {first.get('msg')}")


# ---------------------------------------------------------------------------
# color analysis
# ---------------------------------------------------------------------------


def _reference(slot_key: str) -> float:
    return TEXT_REFERENCE if slot_key in TEXT_SLOTS else UI_REFERENCE


def _measured(
    slot_key: str, color: str, surfaces: dict, app_colors: dict
) -> dict | None:
    """The worst of the grounds this slot can be drawn on, with it named."""
    group_key, _, _slot = slot_key.partition(".")

    if slot_key == "surfaces.on_surface_variant":
        # the pair the theme itself declares, and it renders: the tooltip label
        # on the tooltip fill
        grounds = {"surface_variant": surfaces["surface_variant"]}
    elif group_key not in GROUP_GROUNDS:
        return None
    else:
        grounds = {name: surfaces[name] for name in GROUP_GROUNDS[group_key]}
        if slot_key in BAND_SLOTS:
            grounds["mutedbg"] = app_colors["mutedbg"]

    against, ratio = min(
        ((name, contrast_ratio(color, ground)) for name, ground in grounds.items()),
        key=lambda pair: pair[1],
    )

    return {
        "measured_against": against,
        # rounded DOWN, so a ratio that is under the reference cannot be
        # reported as a number that reads as meeting it (2.9953 -> 2.99)
        "ratio": math.floor(ratio * 100) / 100,
        "wcag_reference": _reference(slot_key),
    }


def analyze_theme(template: Theme) -> dict:
    """Color names and measured contrast for every slot of a theme.

    The agent cannot see the theme it is writing, so what can be computed is
    computed: WCAG ratios and bucketed OKLCH names, both deterministic. What
    cannot be computed from the theme alone - which surface a slot is really
    drawn on - is named as unmeasured rather than guessed at.
    """
    colors = template.colors.model_dump()
    surfaces = colors["surfaces"]

    slots: dict[str, dict] = {}
    unmeasured: dict[str, str] = {}
    low_contrast: list[str] = []

    for group_key, group_colors in colors.items():
        for slot, color in group_colors.items():
            slot_key = f"{group_key}.{slot}"
            entry: dict[str, Any] = {"name": describe_color(color)}

            if slot_key in UNMEASURED_GROUNDS:
                unmeasured[slot_key] = UNMEASURED_GROUNDS[slot_key]
                slots[slot_key] = entry
                continue

            measured = _measured(slot_key, color, surfaces, colors["app"])
            if measured:
                entry["contrast"] = measured
                if measured["ratio"] < measured["wcag_reference"]:
                    low_contrast.append(
                        f"{slot_key} {color} measures {measured['ratio']}:1 against "
                        f"{measured['measured_against']}, the worst of the fills it "
                        f"is drawn on, under the "
                        f"{measured['wcag_reference']}:1 WCAG asks of what it paints"
                    )
            slots[slot_key] = entry

    return {
        "slots": slots,
        "contrast_note": CONTRAST_NOTE,
        "unmeasured": unmeasured,
        "low_contrast": low_contrast,
        # how far apart the two grounds are. No floor: the shipped themes sit at
        # 1.16 (dark) and 1.06 (light), so this says whether cards separate from
        # the page the way they do there, not whether anything passes
        "surface_separation": round(
            contrast_ratio(surfaces["surface"], surfaces["background"]), 2
        ),
    }


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------


def list_themes(scene: "Scene") -> list[dict] | str:
    """List every theme template with its group, mode and lock state."""
    collection = template_collection(scene)
    active = get_config().appearance.theme
    themes = _themes(collection)

    if not themes:
        return "No theme templates exist yet."

    return [_theme_entry(group, template, active) for group, template in themes]


def read_theme(scene: "Scene", theme_id: str) -> dict | str:
    """Return one theme in full - every color slot, styling, mode and scheme."""
    collection = template_collection(scene)
    try:
        group, template = _resolve_theme(collection, theme_id)
    except ValueError as exc:
        return str(exc)

    payload = _theme_entry(group, template, get_config().appearance.theme)
    payload.update(
        colors=template.colors.model_dump(),
        appearance=template.appearance.model_dump(),
        code_editor=template.code_editor,
        **analyze_theme(template),
    )
    return payload


def _written_contrast(template: Theme, changed: dict | None = None) -> dict:
    """What a write reports back about how the theme reads.

    The per-slot table belongs to `read_theme`; a write returns what it left
    below the WCAG reference (so the agent can correct itself without another
    read), the measurements for the slots it touched, and the separation of the
    two grounds, which a color write can flatten.
    """
    analysis = analyze_theme(template)
    report: dict[str, Any] = {
        "low_contrast": analysis["low_contrast"],
        "surface_separation": analysis["surface_separation"],
    }

    if changed:
        touched = {}
        for key in changed:
            if not key.startswith("colors."):
                continue
            slot_key = key.split(".", 1)[1]
            entry = analysis["slots"].get(slot_key, {})
            if "contrast" in entry:
                touched[slot_key] = entry["contrast"]
            elif slot_key in analysis["unmeasured"]:
                touched[slot_key] = {"unmeasured": analysis["unmeasured"][slot_key]}
        if touched:
            report["contrast_written"] = touched

    return report


# ---------------------------------------------------------------------------
# writes
# ---------------------------------------------------------------------------


async def create_theme(
    scene: "Scene",
    name: str,
    group: str,
    base_theme: str | None = None,
    colors: dict | None = None,
    appearance: dict | None = None,
    dark: bool | None = None,
    code_editor: str | None = None,
    templates_dirty: bool = False,
) -> dict | str:
    """Create a theme template, seeded from ``base_theme`` and then patched.

    Every slot the new theme carries comes from the base theme (the active one
    unless another is named), so the result is always a complete theme rather
    than a handful of colors on top of the built-in defaults.
    """
    conflict = templates_dirty_conflict(templates_dirty)
    if conflict:
        return conflict

    name = (name or "").strip()
    if not TEMPLATE_NAME_RE.fullmatch(name):
        return (
            "A theme name may only hold letters, digits, spaces and underscores, "
            f"got '{name}'."
        )

    group_name = (group or "").strip()
    if not group_name:
        return (
            "Name the template group the theme should go into. Existing groups are "
            "listed by list_themes; an unknown name creates the group."
        )
    if GROUP_NAME_INVALID_RE.search(group_name) or group_name.strip(". ") == "":
        return f"'{group_name}' is not a valid template group name."

    manager = scene.world_state_manager
    collection = template_collection(scene)

    base_ref = base_theme or get_config().appearance.theme
    if base_ref:
        try:
            _base_group, base = _resolve_theme(collection, base_ref)
        except ValueError as exc:
            return str(exc)
    else:
        base = Theme(name=name)

    target = find_group(collection, group_name)
    if target and is_shipped(target):
        return (
            f"'{target.name}' is a group that ships with Talemate and does not take "
            "new templates. Name a group of the user's own instead - an unknown name "
            "creates it."
        )
    if target and any(
        isinstance(sibling, Theme) and sibling.name.strip().lower() == name.lower()
        for sibling in target.templates.values()
    ):
        return (
            f"Group '{target.name}' already holds a theme called '{name}'. Update that "
            "one, or pick another name."
        )

    template = base.model_copy(deep=True)
    template.name = name
    template.uid = str(uuid.uuid4())
    template.locked = False
    template.favorite = False
    template.instructions = None

    try:
        template, changes = _patched(template, colors, appearance, dark, code_editor)
    except ValueError as exc:
        return str(exc)

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
        "theme_id": _theme_id(template),
        "name": template.name,
        "group": target.name,
        "group_created": created_group,
        "based_on": base.name if base_ref else "the built-in defaults",
        "changed": sorted(changes),
        **_written_contrast(template, changed=changes),
    }


async def update_theme(
    scene: "Scene",
    theme_id: str,
    colors: dict | None = None,
    appearance: dict | None = None,
    dark: bool | None = None,
    code_editor: str | None = None,
    templates_dirty: bool = False,
) -> dict | str:
    """Change the named slots of an existing theme, leaving the rest alone."""
    conflict = templates_dirty_conflict(templates_dirty)
    if conflict:
        return conflict

    collection = template_collection(scene)
    try:
        group, template = _resolve_theme(collection, theme_id)
    except ValueError as exc:
        return str(exc)

    locked = _locked_conflict(template)
    if locked:
        return locked

    if is_shipped(group):
        return (
            f"'{template.name}' lives in '{group.name}', a group that ships with "
            "Talemate. Copy it into a group of the user's own with create_theme "
            f"(base_theme '{_theme_id(template)}') and change the copy."
        )

    try:
        patched, changes = _patched(template, colors, appearance, dark, code_editor)
    except ValueError as exc:
        return str(exc)

    if not changes:
        return f"'{template.name}' already holds those values - nothing was changed."

    await scene.world_state_manager.save_template(patched)

    active = _theme_id(patched) == get_config().appearance.theme
    result = {
        "updated": True,
        "theme_id": _theme_id(patched),
        "name": patched.name,
        "group": group.name,
        "changes": changes,
        "active": active,
        **_written_contrast(patched, changed=changes),
    }

    if active and any(key.startswith("appearance.") for key in changes):
        result["styling_not_live"] = STYLING_NOT_LIVE

    return result


async def apply_theme(
    scene: "Scene",
    theme_id: str,
    templates_dirty: bool = False,
    app_settings_dirty: bool = False,
) -> dict | str:
    """Make a theme the active one and repaint the application with it."""
    conflict = templates_dirty_conflict(
        templates_dirty
    ) or _app_settings_dirty_conflict(app_settings_dirty)
    if conflict:
        return conflict

    collection = template_collection(scene)
    try:
        _group, template = _resolve_theme(collection, theme_id)
    except ValueError as exc:
        return str(exc)

    applied = await scene.world_state_manager.apply_template_theme(template)
    if not applied:
        return f"'{template.name}' could not be applied."

    return {
        "applied": True,
        "theme_id": applied.theme_id,
        "name": applied.name,
        **_written_contrast(template),
        "note": (
            "The theme's message styling replaced the styling in the appearance "
            "settings. Colors the user set by hand there keep overriding the theme "
            "until they reset them."
        ),
    }
