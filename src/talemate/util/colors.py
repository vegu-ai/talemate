import random

__all__ = [
    "COLORS",
    "COLOR_NAMES",
    "COLOR_MAP",
    "SPECIAL_COLOR_NAMES",
    "ALL_COLOR_NAMES",
    "random_color",
    "unique_random_colors",
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

SPECIAL_COLOR_NAMES = ["narrator", "actor", "director", "time", "context_investigation"]

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
