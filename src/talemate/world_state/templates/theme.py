import re
from typing import TYPE_CHECKING

import pydantic
import structlog

from talemate.world_state.templates.base import (
    Collection,
    Template,
    register,
)

if TYPE_CHECKING:
    from talemate.config.schema import Config

__all__ = [
    "AppliedTheme",
    "Theme",
    "ThemeColors",
    "ThemeAppearance",
    "AppColors",
    "NodeEditorColors",
    "MessageColors",
    "ChatColors",
    "SurfaceColors",
    "ThemeMessageStyle",
    "HidableThemeMessageStyle",
    "ThemeMarkupStyle",
    "resolve_theme",
    "invalidate_theme_cache",
]

log = structlog.get_logger("world-state.templates.theme")

COLOR_VALID_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class ColorGroup(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(validate_default=True)

    @pydantic.field_validator("*")
    @classmethod
    def _validate_color(cls, v: str) -> str:
        # a yaml block scalar appends a newline - strip it so a hand authored
        # theme still loads, and store a value the frontend can use verbatim
        v = v.strip()
        if not COLOR_VALID_RE.fullmatch(v):
            raise ValueError(f"Color must be in #RRGGBB form, got: {v}")
        return v


class AppColors(ColorGroup):
    primary: str = "#9575CD"
    secondary: str = "#FF5722"
    delete: str = "#D32F2F"
    cancel: str = "#B0BEC5"
    muted: str = "#9E9E9E"
    mutedheader: str = "#BDBDBD"
    mutedbg: str = "#212121"
    normal: str = "#9E9E9E"
    unsaved: str = "#FFD54F"
    favorite: str = "#FFD740"
    dirty: str = "#FFB74D"
    instructions: str = "#FFE0B2"
    persona: str = "#F48FB1"
    highlight1: str = "#9FA8DA"
    highlight2: str = "#CE93D8"
    highlight3: str = "#C5E1A5"
    highlight4: str = "#EF5350"
    highlight5: str = "#FFE082"
    highlight6: str = "#FFCC80"
    highlight7: str = "#90CAF9"
    subdued1: str = "#303F9F"
    subdued2: str = "#7B1FA2"
    subdued3: str = "#689F38"
    subdued4: str = "#D32F2F"
    subdued5: str = "#FFA000"
    subdued6: str = "#F57C00"
    subdued7: str = "#1976D2"
    enabled: str = "#81C784"
    disabled: str = "#E57373"


class NodeEditorColors(ColorGroup):
    nodeeditorbg: str = "#616161"
    core_node: str = "#78909C"
    core_node_selected: str = "#78909C"
    template_node: str = "#A1887F"
    template_node_selected: str = "#A1887F"
    scene_node: str = "#9575CD"
    scene_node_selected: str = "#7E57C2"
    locked_node_selected: str = "#78909C"


class MessageColors(ColorGroup):
    # these slots own the message text, so chrome that used to take a vuetify
    # value follows them rather than the other way around
    narrator: str = "#A180AE"
    actor: str = "#B39DDB"
    director: str = "#FF5722"
    time: str = "#FFECB3"
    context_investigation: str = "#D5C0A1"
    information: str = "#BA8574"
    quotes: str = "#FFFFFF"
    parentheses: str = "#DB9DC2"
    brackets: str = "#DC5D5D"
    emphasis: str = "#B39DDB"
    entities: str = "#FFE082"
    play_audio: str = "#FBC02D"
    avatar_border: str = "#424242"
    card_border: str = "#424242"
    defaultBadge: str = "#E64A19"


class ChatColors(ColorGroup):
    dchat_msg_director: str = "#FF8A65"
    dchat_msg_user: str = "#B39DDB"
    dchat_msg_action_result: str = "#FFCCBC"
    dchat_msg_loading: str = "#FF7043"
    dchat_msg_compaction: str = "#616161"
    dchat_msg_code: str = "#FFCCBC"
    hchat_msg_help: str = "#90A4AE"
    hchat_msg_user: str = "#B39DDB"
    hchat_msg_doc_result: str = "#64B5F6"


class SurfaceColors(ColorGroup):
    # vuetify's own base slots - the page background and every card surface come
    # from these, so a theme that does not own them cannot be light. the field
    # names carry underscores because the vuetify slots (`surface-bright`) are
    # not valid python identifiers - the frontend hyphenates them again.
    background: str = "#121212"
    surface: str = "#212121"
    surface_bright: str = "#CCBFD6"
    surface_light: str = "#424242"
    surface_variant: str = "#C8C8C8"
    on_surface_variant: str = "#000000"


class ThemeColors(pydantic.BaseModel):
    app: AppColors = pydantic.Field(default_factory=AppColors)
    node_editor: NodeEditorColors = pydantic.Field(default_factory=NodeEditorColors)
    messages: MessageColors = pydantic.Field(default_factory=MessageColors)
    chats: ChatColors = pydantic.Field(default_factory=ChatColors)
    surfaces: SurfaceColors = pydantic.Field(default_factory=SurfaceColors)


class ThemeMessageStyle(pydantic.BaseModel):
    italic: bool = False
    bold: bool = False


class HidableThemeMessageStyle(ThemeMessageStyle):
    show: bool = True


class ThemeMarkupStyle(ThemeMessageStyle):
    override_color: bool = True
    show: bool = True


class ThemeAppearance(pydantic.BaseModel):
    narrator: ThemeMessageStyle = pydantic.Field(default_factory=ThemeMessageStyle)
    actor: ThemeMessageStyle = pydantic.Field(default_factory=ThemeMessageStyle)
    director: HidableThemeMessageStyle = pydantic.Field(
        default_factory=HidableThemeMessageStyle
    )
    time: ThemeMessageStyle = pydantic.Field(default_factory=ThemeMessageStyle)
    context_investigation: HidableThemeMessageStyle = pydantic.Field(
        default_factory=HidableThemeMessageStyle
    )
    information: ThemeMessageStyle = pydantic.Field(default_factory=ThemeMessageStyle)
    quotes: ThemeMarkupStyle = pydantic.Field(default_factory=ThemeMarkupStyle)
    parentheses: ThemeMarkupStyle = pydantic.Field(default_factory=ThemeMarkupStyle)
    brackets: ThemeMarkupStyle = pydantic.Field(default_factory=ThemeMarkupStyle)
    emphasis: ThemeMarkupStyle = pydantic.Field(default_factory=ThemeMarkupStyle)
    entities: ThemeMarkupStyle = pydantic.Field(default_factory=ThemeMarkupStyle)

    backdrop_panel_opacity: float = pydantic.Field(default=0.8, ge=0.0, le=1.0)
    backdrop_text_shadow: bool = True


@register("theme")
class Theme(Template):
    """
    Template for the application theme.

    Colors and text styling only - workflow preferences (message assets, auto
    attaching of assets) deliberately stay in the appearance config so they
    survive a theme switch.
    """

    template_type: str = "theme"
    colors: ThemeColors = pydantic.Field(default_factory=ThemeColors)
    appearance: ThemeAppearance = pydantic.Field(default_factory=ThemeAppearance)
    # drives vuetify's color-scheme, overlay multipliers and the stock theme
    # variables (border color, emphasis opacities). NOT the on-* text colors -
    # those come from APCA contrast against each color itself, so they follow
    # the surfaces group rather than this flag.
    dark: bool = True

    def resolved(self) -> dict:
        return {
            "colors": self.colors.model_dump(),
            "appearance": self.appearance.model_dump(),
            "dark": self.dark,
        }


class AppliedTheme(pydantic.BaseModel):
    theme_id: str
    name: str


def default_theme() -> dict:
    return Theme(name="Default").resolved()


# theme id -> the template it resolves to, `None` for ids that do not resolve.
# `resolve_theme` runs on every config change (which includes client status
# writes during normal play) and loading a collection walks and parses the
# whole template directory, so the lookup is only ever done once per id.
_RESOLVED_THEMES: dict[str, Theme | None] = {}


def invalidate_theme_cache():
    """
    Drops the cached theme lookups.

    Must be called whenever a template group file is written or removed -
    `WorldStateManager` does this for every mutation it owns.
    """

    _RESOLVED_THEMES.clear()


def _find_theme(theme_id: str, collection: Collection | None) -> Theme | None:
    try:
        if collection is None:
            collection = Collection.load()
        template = collection.find_template_by_id(theme_id)
    except Exception as exc:
        log.warning("theme could not be loaded", theme=theme_id, error=str(exc))
        return None

    if not isinstance(template, Theme):
        log.warning("theme not found", theme=theme_id)
        return None

    return template


def resolve_theme(config: "Config", collection: Collection | None = None) -> dict:
    """
    Resolves the active theme to
    `{"colors": {...}, "appearance": {...}, "dark": bool}`.

    Falls back to the built-in default for anything that does not resolve to a
    theme template - the app must never end up rendering unstyled.

    An explicitly passed collection is always the source of truth and neither
    reads nor fills the cache.
    """

    theme_id = config.appearance.theme

    if not theme_id:
        return default_theme()

    if collection is not None:
        template = _find_theme(theme_id, collection)
    else:
        if theme_id not in _RESOLVED_THEMES:
            _RESOLVED_THEMES[theme_id] = _find_theme(theme_id, None)
        template = _RESOLVED_THEMES[theme_id]

    if template is None:
        return default_theme()

    return template.resolved()
