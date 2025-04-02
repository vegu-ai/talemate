import random

__all__ = [
    "COLORS",
    "random_color",
]

COLORS = [
    # Base colors
    "#F44336",  # red
    "#E91E63",  # pink
    "#9C27B0",  # purple
    "#673AB7",  # deep-purple
    "#3F51B5",  # indigo
    "#2196F3",  # blue
    "#03A9F4",  # light-blue
    "#00BCD4",  # cyan
    "#009688",  # teal
    "#4CAF50",  # green
    "#8BC34A",  # light-green
    "#CDDC39",  # lime
    "#FFEB3B",  # yellow
    "#FFC107",  # amber
    "#FF9800",  # orange
    "#FF5722",  # deep-orange
    "#795548",  # brown
    "#607D8B",  # blue-grey
    "#9E9E9E",  # grey
    
    # Lighten-3 colors
    "#EF9A9A",  # red-lighten-3
    "#F48FB1",  # pink-lighten-3
    "#CE93D8",  # purple-lighten-3
    "#B39DDB",  # deep-purple-lighten-3
    "#9FA8DA",  # indigo-lighten-3
    "#90CAF9",  # blue-lighten-3
    "#81D4FA",  # light-blue-lighten-3
    "#80DEEA",  # cyan-lighten-3
    "#80CBC4",  # teal-lighten-3
    "#A5D6A7",  # green-lighten-3
    "#C5E1A5",  # light-green-lighten-3
    "#E6EE9C",  # lime-lighten-3
    "#FFF59D",  # yellow-lighten-3
    "#FFE082",  # amber-lighten-3
    "#FFCC80",  # orange-lighten-3
    "#FFAB91",  # deep-orange-lighten-3
    "#BCAAA4",  # brown-lighten-3
    "#B0BEC5",  # blue-grey-lighten-3
    "#EEEEEE",  # grey-lighten-3
    
    # Darken-3 colors
    "#C62828",  # red-darken-3
    "#AD1457",  # pink-darken-3
    "#6A1B9A",  # purple-darken-3
    "#4527A0",  # deep-purple-darken-3
    "#283593",  # indigo-darken-3
    "#1565C0",  # blue-darken-3
    "#0277BD",  # light-blue-darken-3
    "#00838F",  # cyan-darken-3
    "#00695C",  # teal-darken-3
    "#2E7D32",  # green-darken-3
    "#558B2F",  # light-green-darken-3
    "#9E9D24",  # lime-darken-3
    "#F9A825",  # yellow-darken-3
    "#FF8F00",  # amber-darken-3
    "#EF6C00",  # orange-darken-3
    "#D84315",  # deep-orange-darken-3
    "#4E342E",  # brown-darken-3
    "#37474F",  # blue-grey-darken-3
    "#424242",  # grey-darken-3
]


def random_color() -> str:
    return random.choice(COLORS)