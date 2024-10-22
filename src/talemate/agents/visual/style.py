import pydantic
import structlog

__all__ = [
    "Style",
    "STYLE_MAP",
    "THEME_MAP",
    "MAJOR_STYLES",
    "combine_styles",
]

STYLE_MAP = {}
THEME_MAP = {}
MAJOR_STYLES = {}

log = structlog.get_logger("talemate.agents.visual.style")


class Style(pydantic.BaseModel):
    keywords: list[str] = pydantic.Field(default_factory=list)
    negative_keywords: list[str] = pydantic.Field(default_factory=list)

    @property
    def positive_prompt(self):
        return ", ".join(self.keywords)

    @property
    def negative_prompt(self):
        return ", ".join(self.negative_keywords)

    def __str__(self):
        return f"POSITIVE: {self.positive_prompt}\nNEGATIVE: {self.negative_prompt}"

    def load(self, prompt: str, negative_prompt: str = ""):
        self.keywords = prompt.split(", ")
        self.negative_keywords = negative_prompt.split(", ")

        # loop through keywords and drop any starting with "no " and add to negative_keywords
        # with "no " removed
        for kw in self.keywords:
            kw = kw.strip()
            log.debug("Checking keyword", keyword=kw)
            if kw.startswith("no "):
                log.debug("Transforming negative keyword", keyword=kw, to=kw[3:])
                self.keywords.remove(kw)
                self.negative_keywords.append(kw[3:])

        return self

    def prepend(self, *styles):
        for style in styles:
            for idx in range(len(style.keywords) - 1, -1, -1):
                kw = style.keywords[idx]
                if kw not in self.keywords:
                    self.keywords.insert(0, kw)

            for idx in range(len(style.negative_keywords) - 1, -1, -1):
                kw = style.negative_keywords[idx]
                if kw not in self.negative_keywords:
                    self.negative_keywords.insert(0, kw)

        return self

    def append(self, *styles):
        for style in styles:
            for kw in style.keywords:
                if kw not in self.keywords:
                    self.keywords.append(kw)

            for kw in style.negative_keywords:
                if kw not in self.negative_keywords:
                    self.negative_keywords.append(kw)

        return self

    def copy(self):
        return Style(
            keywords=self.keywords.copy(),
            negative_keywords=self.negative_keywords.copy(),
        )


# Almost taken straight from some of the fooocus style presets, credit goes to the original author

STYLE_MAP["digital_art"] = Style(
    keywords="in the style of a digital artwork, masterpiece, best quality, high detail".split(", "),
    negative_keywords="text, watermark, low quality, blurry, photo".split(", "),
)

STYLE_MAP["concept_art"] = Style(
    keywords="in the style of concept art, conceptual sketch, masterpiece, best quality, high detail".split(
        ", "
    ),
    negative_keywords="text, watermark, low quality, blurry, photo".split(", "),
)

STYLE_MAP["ink_illustration"] = Style(
    keywords="in the style of ink illustration, painting, masterpiece, best quality".split(", "),
    negative_keywords="text, watermark, low quality, blurry, photo".split(", "),
)

STYLE_MAP["anime"] = Style(
    keywords="in the style of anime, masterpiece, best quality, illustration".split(", "),
    negative_keywords="text, watermark, low quality, blurry, photo, 3d".split(", "),
)

STYLE_MAP["graphic_novel"] = Style(
    keywords="(stylized by Enki Bilal:0.7), best quality, graphic novels, detailed linework, digital art".split(
        ", "
    ),
    negative_keywords="text, watermark, low quality, blurry, photo, 3d, cgi".split(
        ", "
    ),
)

STYLE_MAP["photo"] = Style(
    keywords="photo, photograph, RAW photo, DLSS".split(", "),
    negative_keywords="digital art, drawing, illustration, painting, concept art".split(
        ", "
    ),
)

STYLE_MAP["character_portrait"] = Style(keywords="solo, looking at viewer".split(", "))

STYLE_MAP["environment"] = Style(
    keywords="scenery, environment, background, postcard".split(", "),
    negative_keywords="character, portrait, looking at viewer, people".split(", "),
)

MAJOR_STYLES = [
    {"value": "anime", "label": "Anime"},
    {"value": "concept_art", "label": "Concept Art"},
    {"value": "digital_art", "label": "Digital Art"},
    {"value": "graphic_novel", "label": "Graphic Novel"},
    {"value": "ink_illustration", "label": "Ink Illustration"},
    {"value": "photo", "label": "Photo"},
]


def combine_styles(*styles):
    keywords = []
    for style in styles:
        keywords.extend(style.keywords)
    return Style(keywords=list(set(keywords)))
