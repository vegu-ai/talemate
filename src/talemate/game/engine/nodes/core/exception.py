import pydantic

__all__ = [
    "ExceptionWrapper",
]

class ExceptionWrapper(pydantic.BaseModel):
    name: str
    message: str