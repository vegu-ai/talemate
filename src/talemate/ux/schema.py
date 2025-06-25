import pydantic

__all__ = [
    "Note",
]

class Note(pydantic.BaseModel):
    text: str
    title: str = None
    color: str = "muted"
    icon: str = "mdi-information-outline"