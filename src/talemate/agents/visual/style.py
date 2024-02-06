import pydantic

__all__ = [
    "Style",
    "STYLE_MAP",
    "THEME_MAP",
    "combine_styles",
]

STYLE_MAP = {}
THEME_MAP = {}

class Style(pydantic.BaseModel):
    keywords: list[str]

# Almost taken straight from some of the fooocus style presets, credit goes to the original author

STYLE_MAP["digital_art"] = Style(
    keywords="masterpiece, best quality, intricate, high detail".split(", ")
)

STYLE_MAP["concept_art"] = Style(
    keywords="masterpiece, best quality, concept art, video game art".split(", ")
)

STYLE_MAP["anime"] = Style(
    keywords="anime, masterpiece, best quality, illustration".split(", ")
)

def combine_styles(*styles):
    keywords = []
    for style in styles:
        keywords.extend(style.keywords)
    return Style(keywords=list(set(keywords)))