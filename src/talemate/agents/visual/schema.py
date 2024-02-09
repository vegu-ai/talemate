import pydantic

__all__ = [
    "RenderSettings",
    "Resolution",
    "RESOLUTION_MAP",
]

RESOLUTION_MAP = {}

class RenderSettings(pydantic.BaseModel):
    type_model: str = "sdxl"
    steps: int = 40
    

class Resolution(pydantic.BaseModel):
    width: int
    height: int
    
    
RESOLUTION_MAP["sdxl"] = {
    "portrait": Resolution(width=832, height=1216),
    "landscape": Resolution(width=1216, height=832),
    "square": Resolution(width=1024, height=1024),
}

RESOLUTION_MAP["sd15"] = {
    "portrait": Resolution(width=512, height=768),
    "landscape": Resolution(width=768, height=512),
    "square": Resolution(width=768, height=768),
}

