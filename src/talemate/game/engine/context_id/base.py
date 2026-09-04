"""
Context ID classes and functions

Unified way of describing where context information is stored.
"""

from __future__ import annotations

from typing import ClassVar, TYPE_CHECKING, Any, Callable, Iterable
import hashlib
import pydantic
import structlog

if TYPE_CHECKING:
    from talemate.tale_mate import Scene


__all__ = [
    "ContextID",
    "ContextIDHandler",
    "ContextIDItem",
    "ContextIDHandlerError",
    "ContextIDValidationError",
    "ContextIDInvalidContextType",
    "ContextIDNoHandlerFound",
    "ContextIDInvalidIDString",
    "ContextIDItemReadOnly",
    "ContextIDMeta",
    "ContextIDMetaGroup",
    # functions
    "compress_name",
    "context_id_item_by_name",
    "context_id_path_str",
    "register_context_id_type",
    "register_context_id_handler",
    "register_context_id_meta",
    "get_context_id_type",
    "context_id_item_from_string",
    "context_id_handler_from_string",
    "context_id_from_string",
    "context_id_from_object",
    "registered_context_id_types",
    "get_meta_groups",
    # globals
    "CONTEXT_ID_TYPES",
    "CONTEXT_ID_PATH_HANDLERS",
    "CONTEXT_ID_META",
]

log = structlog.get_logger("talemate.game.engine.context_id")


CONTEXT_ID_TYPES: dict[str, type["ContextID"]] = {}

CONTEXT_ID_PATH_HANDLERS: dict[str, "ContextIDHandler"] = {}

CONTEXT_ID_META: dict[str, ContextIDMetaGroup] = {}


class ContextIDValidationError(ValueError):
    """Base exception for context ID validation related errors."""

    def __init__(self, context_id_str: str):
        self.context_id_str = context_id_str
        super().__init__(f"Invalid context ID string: {context_id_str}")


class ContextIDHandlerError(ContextIDValidationError):
    """Base exception for context handler related errors."""

    pass


class ContextIDInvalidContextType(ContextIDValidationError):
    """Exception raised when the context type is invalid."""

    def __init__(self, context_id_str: str, context_type: str):
        self.context_id_str = context_id_str
        super().__init__(
            f"Invalid context ID string: {context_id_str} - {context_type}"
        )


class ContextIDNoHandlerFound(ContextIDValidationError):
    """Exception raised when no handler is found for the context type."""

    def __init__(self, context_id_str: str, context_type: str):
        self.context_id_str = context_id_str
        log.error(
            "No handler found for context ID string",
            context_id_str=context_id_str,
            context_type=context_type,
            handlers=CONTEXT_ID_PATH_HANDLERS,
        )
        super().__init__(
            f"No handler found for context ID string: {context_id_str} - {context_type}"
        )


class ContextIDInvalidIDString(ContextIDValidationError):
    """Exception raised when the context ID string is invalid."""

    def __init__(self, context_id_str: str, error_details: str):
        self.context_id_str = context_id_str
        super().__init__(
            f"Invalid context ID string: {context_id_str} - {error_details}"
        )


class ContextIDItemReadOnly(ContextIDValidationError):
    """Context ID item that is read only."""

    def __init__(self, context_id_str: str):
        self.context_id_str = context_id_str
        super().__init__(f"Context ID item is read only: {context_id_str}")


def compress_name(name: str, length: int = 12) -> str:
    """Compress a name to a shorter SHA256-based identifier."""
    return hashlib.sha256(name.encode("utf-8")).hexdigest()[:length]


def register_context_id_type(context_id_type: "ContextID") -> type["ContextID"]:
    CONTEXT_ID_TYPES[context_id_type.context_type] = context_id_type
    return context_id_type


def register_context_id_handler(
    context_id_path_handler: "ContextIDHandler",
) -> type["ContextIDHandler"]:
    for context_type in context_id_path_handler.context_types:
        CONTEXT_ID_PATH_HANDLERS[context_type] = context_id_path_handler
    return context_id_path_handler


def register_context_id_meta(context_id_meta: ContextIDMetaGroup) -> ContextIDMetaGroup:
    CONTEXT_ID_META[context_id_meta.context_id] = context_id_meta
    return context_id_meta


def get_context_id_type(context_type: str) -> type["ContextID"]:
    return CONTEXT_ID_TYPES[context_type]


def registered_context_id_types() -> list[str]:
    return list(CONTEXT_ID_TYPES.keys())


def context_id_path_str(context_id_str: str) -> str:
    """Return the path portion of a context ID string, dots and colons intact."""
    return _parts_raw(context_id_str)[1]


def context_id_item_by_name(
    items: Iterable["ContextIDItem"], name: str
) -> "ContextIDItem | None":
    """
    Find an item by its readable name, in order of precedence: the name exactly
    as stored, then the name ignoring outer whitespace, then ignoring case as
    well. Every candidate is ranked in one pass, so two names that differ only
    in outer whitespace do not resolve by iteration order.
    """
    stripped = name.strip()
    stripped_match = None
    case_insensitive_match = None

    for item in items:
        if item.name == name:
            return item

        item_name = item.name.strip()
        if stripped_match is None and item_name == stripped:
            stripped_match = item
        if (
            case_insensitive_match is None
            and item_name.casefold() == stripped.casefold()
        ):
            case_insensitive_match = item

    if stripped_match is not None:
        return stripped_match
    return case_insensitive_match


def _parts_raw(context_id_str: str) -> tuple[str, str]:
    try:
        context_type, path_str = context_id_str.split(":", 1)
        return context_type, path_str
    except Exception as e:
        raise ContextIDInvalidIDString(context_id_str, str(e))


def _parts(context_id_str: str) -> tuple[str, list[str]]:
    context_type, path_str = _parts_raw(context_id_str)
    return context_type, path_str.split(".")


class ContextIDHandler(pydantic.BaseModel):
    context_types: ClassVar[list[str]] = ["context"]

    @classmethod
    def instance_from_path(cls, path: list[str], scene: "Scene") -> "ContextIDHandler":
        raise NotImplementedError("Subclasses must implement this method")

    async def context_id_from_path(
        self, context_type: str, path: list[str], path_str: str, scene: "Scene"
    ) -> "ContextID | None":
        raise NotImplementedError("Subclasses must implement this method")

    async def context_id_item_from_path(
        self, context_type: str, path: list[str], path_str: str, scene: "Scene"
    ) -> "ContextIDItem | None":
        raise NotImplementedError("Subclasses must implement this method")

    async def context_id_item_from_name(
        self, context_type: str, path: list[str], path_str: str, scene: "Scene"
    ) -> "ContextIDItem | None":
        """
        Resolve a context ID whose path carries the readable name instead of the
        compressed identifier. Handlers that compress a name into their path
        implement this so both forms of the ID work.
        """
        return None


class ContextIDItem(pydantic.BaseModel):
    context_type: str
    name: str
    value: str | int | float | bool | list | dict | None

    @property
    def context_id(self) -> "ContextID":
        raise NotImplementedError("Subclasses must implement this method")

    @property
    def compressed_path(self) -> str:
        return self.context_id.path_to_str

    @property
    def human_id(self) -> str:
        raise NotImplementedError("Subclasses must implement this method")

    @property
    def memory_id(self) -> str | None:
        return None

    async def get(self, scene: "Scene") -> Any:
        raise NotImplementedError("Subclasses must implement this method")

    async def set(self, scene: "Scene", value: Any):
        raise NotImplementedError("Subclasses must implement this method")


class ContextIDMeta(pydantic.BaseModel):
    description: str = "Context ID"
    context_id: str = "context"
    permanent: bool = True
    creative: bool = False
    readonly: bool = False


class ContextIDMetaGroup(pydantic.BaseModel):
    context_id: str = "context"
    description: str = "Context ID Group"
    items: list[ContextIDMeta] = pydantic.Field(default_factory=list)


class ContextMetaResult(pydantic.BaseModel):
    context_id: str
    description: str
    creative: bool
    readonly: bool

    @property
    def tags(self) -> str:
        tags = []
        if self.creative:
            tags.append("CREATIVE")
        if self.readonly:
            tags.append("READONLY")
        return ", ".join(tags)


class ContextID(pydantic.BaseModel):
    path: list[str]
    context_type: ClassVar[str] = "context"

    @classmethod
    def make(cls, path: list[str], **kwargs) -> "ContextID":
        return cls(path=path)

    @classmethod
    def from_str(cls, context_id_str: str, scene: "Scene") -> "ContextID":
        raise NotImplementedError("Subclasses must implement this method")

    @property
    def path_to_str(self) -> str:
        path_str = ".".join(self.path)
        return f"{self.context_type}:{path_str}"

    @property
    def context_type_label(self) -> str:
        return self.context_type.replace(".", " ").replace("_", " ").title()

    @property
    def id(self) -> str:
        return self.path_to_str

    def __str__(self) -> str:
        return self.id


def context_id_handler_from_string(
    context_id_str: str,
    scene: "Scene",
) -> ContextIDHandler | None:
    context_type, path = _parts(context_id_str)
    if context_type not in CONTEXT_ID_PATH_HANDLERS:
        raise ContextIDNoHandlerFound(context_id_str, context_type)
    handler_cls = CONTEXT_ID_PATH_HANDLERS[context_type]

    handler = handler_cls.instance_from_path(path, scene)
    return handler


async def context_id_item_from_string(
    context_id_str: str, scene: "Scene"
) -> "ContextIDItem | None":
    context_type, path = _parts(context_id_str)
    handler = context_id_handler_from_string(context_id_str, scene)
    item = await handler.context_id_item_from_path(
        context_type, path, context_id_str, scene
    )
    if item is not None:
        return item
    return await handler.context_id_item_from_name(
        context_type, path, context_id_str, scene
    )


async def context_id_from_string(
    context_id_str: str, scene: "Scene"
) -> "ContextID | None":
    context_id_item = await context_id_item_from_string(context_id_str, scene)
    if context_id_item is None:
        return None
    return context_id_item.context_id


def context_id_from_object(context_type: str, object: Any, **kwargs) -> "ContextID":
    return get_context_id_type(context_type).make(object, **kwargs)


async def get_meta_groups(
    scene, filter_fn: Callable[[ContextIDMeta], bool] = None
) -> dict[str, list[ContextMetaResult]]:
    items: dict[str, list[ContextMetaResult]] = {}
    for group in CONTEXT_ID_META.values():
        group_items = []
        for meta in group.items:
            if filter_fn and not filter_fn(meta):
                continue

            group_items.append(
                ContextMetaResult(
                    context_id=meta.context_id,
                    description=meta.description,
                    creative=meta.creative,
                    readonly=meta.readonly,
                )
            )
        items[group.description] = group_items
    return items
