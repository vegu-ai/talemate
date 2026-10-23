import math
import random

__all__ = [
    "COLORS",
    "COLOR_NAMES",
    "COLOR_MAP",
    "SPECIAL_COLOR_NAMES",
    "ALL_COLOR_NAMES",
    "random_color",
    "unique_random_colors",
    "relative_luminance",
    "contrast_ratio",
    "oklch",
    "describe_color",
]

# Primary mapping of Vue color names to hex codes
COLOR_MAP = {
    # Base colors
    "red": "#F44336",
    "pink": "#E91E63",
    "purple": "#9C27B0",
    "deep-purple": "#673AB7",
    "indigo": "#3F51B5",
    "blue": "#2196F3",
    "light-blue": "#03A9F4",
    "cyan": "#00BCD4",
    "teal": "#009688",
    "green": "#4CAF50",
    "light-green": "#8BC34A",
    "lime": "#CDDC39",
    "yellow": "#FFEB3B",
    "amber": "#FFC107",
    "orange": "#FF9800",
    "deep-orange": "#FF5722",
    "brown": "#795548",
    "blue-grey": "#607D8B",
    "grey": "#9E9E9E",
    # Lighten-3 colors
    "red-lighten-3": "#EF9A9A",
    "pink-lighten-3": "#F48FB1",
    "purple-lighten-3": "#CE93D8",
    "deep-purple-lighten-3": "#B39DDB",
    "indigo-lighten-3": "#9FA8DA",
    "blue-lighten-3": "#90CAF9",
    "light-blue-lighten-3": "#81D4FA",
    "cyan-lighten-3": "#80DEEA",
    "teal-lighten-3": "#80CBC4",
    "green-lighten-3": "#A5D6A7",
    "light-green-lighten-3": "#C5E1A5",
    "lime-lighten-3": "#E6EE9C",
    "yellow-lighten-3": "#FFF59D",
    "amber-lighten-3": "#FFE082",
    "orange-lighten-3": "#FFCC80",
    "deep-orange-lighten-3": "#FFAB91",
    "brown-lighten-3": "#BCAAA4",
    "blue-grey-lighten-3": "#B0BEC5",
    "grey-lighten-3": "#EEEEEE",
    # Darken-3 colors
    "red-darken-3": "#C62828",
    "pink-darken-3": "#AD1457",
    "purple-darken-3": "#6A1B9A",
    "deep-purple-darken-3": "#4527A0",
    "indigo-darken-3": "#283593",
    "blue-darken-3": "#1565C0",
    "light-blue-darken-3": "#0277BD",
    "cyan-darken-3": "#00838F",
    "teal-darken-3": "#00695C",
    "green-darken-3": "#2E7D32",
    "light-green-darken-3": "#558B2F",
    "lime-darken-3": "#9E9D24",
    "yellow-darken-3": "#F9A825",
    "amber-darken-3": "#FF8F00",
    "orange-darken-3": "#EF6C00",
    "deep-orange-darken-3": "#D84315",
    "brown-darken-3": "#4E342E",
    "blue-grey-darken-3": "#37474F",
    "grey-darken-3": "#424242",
}

# Derive lists from the map
COLOR_NAMES = sorted(list(COLOR_MAP.keys()))
COLORS = sorted(list(COLOR_MAP.values()))

SPECIAL_COLOR_NAMES = [
    "narrator",
    "actor",
    "director",
    "time",
    "context_investigation",
    "reinforcement",
    "information",
]

ALL_COLOR_NAMES = SPECIAL_COLOR_NAMES + COLOR_NAMES


def random_color() -> str:
    return random.choice(COLORS)


def unique_random_colors(count: int) -> list[str]:
    """Return a list of unique random colors.

    Args:
        count: Number of unique colors to return

    Returns:
        List of color hex codes. If count exceeds available colors,
        duplicates may be included but colors are still randomized.
    """
    if count <= 0:
        return []

    if count > len(COLORS):
        # If we have more requested colors than available, allow duplicates but still randomize
        return [random.choice(COLORS) for _ in range(count)]
    else:
        # Sample unique colors for each requested color
        return random.sample(COLORS, count)


# ---------------------------------------------------------------------------
# color analysis
# ---------------------------------------------------------------------------

# OKLCH hue in degrees -> the name a reader would use. Calibrated against the
# material palette above: pink lands at 10, red at 29, orange at 64, green at
# 144, blue at 249, purple at 321.
HUE_NAMES = (
    (20, "pink"),
    (33, "red"),
    (75, "orange"),
    (95, "amber"),
    (110, "yellow"),
    (125, "lime"),
    (160, "green"),
    (200, "teal"),
    (225, "cyan"),
    (268, "blue"),
    (285, "indigo"),
    (310, "violet"),
    (345, "purple"),
    (360, "pink"),
)

GREY_NAMES = (
    (0.12, "black"),
    (0.25, "near-black grey"),
    (0.45, "dark grey"),
    (0.72, "grey"),
    (0.88, "light grey"),
    (0.97, "near-white grey"),
    (1.01, "white"),
)

LIGHTNESS_NAMES = (
    (0.12, "near-black"),
    (0.32, "very dark"),
    (0.50, "dark"),
    (0.68, ""),
    (0.85, "light"),
    (0.97, "very light"),
    (1.01, "near-white"),
)

CHROMA_NAMES = (
    (0.06, "muted"),
    (0.12, "soft"),
    (0.20, ""),
    (1.00, "vivid"),
)

ACHROMATIC_CHROMA = 0.02

# a dulled, darker orange-red is a brown to every reader, and no reader calls a
# theme slot "muted dark orange"
BROWN_MAX_CHROMA = 0.09
BROWN_MAX_LIGHTNESS = 0.72


def _channels(color: str) -> tuple[float, float, float]:
    color = color.strip().lstrip("#")
    return tuple(int(color[i : i + 2], 16) / 255 for i in (0, 2, 4))


def _linear(channel: float) -> float:
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def relative_luminance(color: str) -> float:
    """WCAG relative luminance of a `#RRGGBB` color."""
    red, green, blue = (_linear(channel) for channel in _channels(color))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(color: str, other: str) -> float:
    """WCAG 2.x contrast ratio between two `#RRGGBB` colors, 1.0 to 21.0."""
    lighter, darker = sorted(
        (relative_luminance(color), relative_luminance(other)), reverse=True
    )
    return (lighter + 0.05) / (darker + 0.05)


def oklch(color: str) -> tuple[float, float, float]:
    """Convert `#RRGGBB` to OKLCH: perceptual lightness, chroma, hue in degrees.

    Lightness and chroma are perceptually spaced, unlike HSL's, which is what
    makes a name derived from them match what the eye reports.
    """
    red, green, blue = (_linear(channel) for channel in _channels(color))

    long_ = (0.4122214708 * red + 0.5363325363 * green + 0.0514459929 * blue) ** (1 / 3)
    medium = (0.2119034982 * red + 0.6806995451 * green + 0.1073969566 * blue) ** (
        1 / 3
    )
    short = (0.0883024619 * red + 0.2817188376 * green + 0.6299787005 * blue) ** (1 / 3)

    lightness = 0.2104542553 * long_ + 0.7936177850 * medium - 0.0040720468 * short
    green_red = 1.9779984951 * long_ - 2.4285922050 * medium + 0.4505937099 * short
    blue_yellow = 0.0259040371 * long_ + 0.7827717662 * medium - 0.8086757660 * short

    chroma = math.hypot(green_red, blue_yellow)
    hue = math.degrees(math.atan2(blue_yellow, green_red)) % 360

    return lightness, chroma, hue


def _bucket(value: float, buckets: tuple[tuple[float, str], ...]) -> str:
    for edge, name in buckets:
        if value < edge:
            return name
    return buckets[-1][1]


def describe_color(color: str) -> str:
    """A rough, deterministic name for a color - 'muted dark blue'.

    Meant for an LLM reading a palette it cannot see: enough to tell a slate
    blue from a vivid one and to notice that two slots hold the same family.
    """
    lightness, chroma, hue = oklch(color)

    if chroma < ACHROMATIC_CHROMA:
        return _bucket(lightness, GREY_NAMES)

    hue_name = _bucket(hue, HUE_NAMES)
    if (
        hue_name in ("red", "orange")
        and chroma < BROWN_MAX_CHROMA
        and lightness < BROWN_MAX_LIGHTNESS
    ):
        hue_name = "brown"

    parts = [
        _bucket(chroma, CHROMA_NAMES),
        _bucket(lightness, LIGHTNESS_NAMES),
        hue_name,
    ]
    return " ".join(part for part in parts if part)
