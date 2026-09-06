import hashlib
import uuid
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
    model_serializer,
)


def content_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class KnowledgeRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceReference(KnowledgeRecord):
    kind: Literal["message", "summary", "disclosure"]
    id: StrictInt | StrictStr
    revision: int = Field(ge=1, strict=True)
    layer: int = Field(default=0, ge=0, strict=True)
    view_id: str | None = None
    view_revision: int | None = Field(default=None, ge=1, strict=True)

    @model_serializer(mode="wrap")
    def serialize_view_revision(self, handler):
        data = handler(self)
        if self.view_revision is None:
            data.pop("view_revision", None)
        return data

    @model_validator(mode="after")
    def valid_identity(self):
        if self.kind == "message":
            if type(self.id) is not int or self.id < 1:
                raise ValueError("Message source IDs must be positive integers")
        elif not isinstance(self.id, str) or not self.id.strip():
            raise ValueError(
                "Summary and disclosure source IDs must be nonempty strings"
            )
        if self.kind != "summary" and self.layer:
            raise ValueError("Only summary sources have layers")
        if self.view_id is not None and not self.view_id.strip():
            raise ValueError("View IDs must be nonempty")
        if self.view_revision is not None and self.view_id is None:
            raise ValueError("View revisions require a view ID")
        if self.kind == "disclosure" and self.view_id is not None:
            raise ValueError(
                "Disclosures are independent sources, not perspective views"
            )
        return self

    @property
    def key(self) -> tuple[str, str | int, int]:
        return self.kind, self.id, self.layer


class Acquisition(KnowledgeRecord):
    order: int = Field(ge=1, strict=True)
    ts: int = Field(strict=True)


class AudienceRecord(KnowledgeRecord):
    audience: tuple[StrictStr, ...] = Field(min_length=1)

    @field_validator("audience")
    @classmethod
    def valid_audience(cls, value):
        if any(not name.strip() or name != name.strip() for name in value):
            raise ValueError(
                "Audience names must be nonempty canonical character names"
            )
        if len(set(value)) != len(value):
            raise ValueError("Duplicate audience name")
        return value


class PassageProvenance(KnowledgeRecord):
    message_id: int = Field(ge=1, strict=True)
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    revision: int | None = Field(default=None, ge=1, strict=True)


class PerspectiveOutput(AudienceRecord):
    id: str | None = Field(default=None, min_length=1)
    status: Literal["ready", "pending", "failed", "omitted"]
    text: StrictStr | None = None
    sources: tuple[SourceReference, ...] = ()
    passage_provenance: tuple[PassageProvenance, ...] = ()

    @model_serializer(mode="wrap")
    def serialize_provenance(self, handler):
        data = handler(self)
        if not self.passage_provenance:
            data.pop("passage_provenance", None)
        return data

    @field_validator("id")
    @classmethod
    def nonempty_identity(cls, value):
        if value is not None and not value.strip():
            raise ValueError("View IDs must be nonempty")
        return value

    @model_validator(mode="after")
    def valid_content(self):
        if self.status == "ready":
            if self.text is None or not self.text.strip():
                raise ValueError(
                    "A ready perspective requires complete replacement text"
                )
        elif self.text is not None:
            raise ValueError("Only a ready perspective may carry text")
        return self


class PerspectiveView(PerspectiveOutput):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex, min_length=1)
    revision: int = Field(default=1, ge=1, strict=True)

    def invalidated(self) -> "PerspectiveView":
        return self.model_copy(
            update={"revision": self.revision + 1, "status": "pending", "text": None}
        )


class SourcePerspectives(KnowledgeRecord):
    revision: int = Field(default=1, ge=1, strict=True)
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    acquired: Acquisition
    views: tuple[PerspectiveView, ...] = ()

    @model_validator(mode="after")
    def unambiguous_views(self):
        audience = [name for view in self.views for name in view.audience]
        if len(audience) != len(set(audience)):
            raise ValueError(
                "A character cannot have overlapping perspective assignments"
            )
        ids = [view.id for view in self.views]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate perspective view ID")
        return self

    def invalidated(self, text: str) -> "SourcePerspectives":
        return SourcePerspectives(
            revision=self.revision + 1,
            content_digest=content_digest(text),
            acquired=self.acquired,
            views=tuple(view.invalidated() for view in self.views),
        )


class PerspectiveSourceModel(BaseModel):
    knowledge: SourcePerspectives | None = None

    @model_serializer(mode="wrap")
    def serialize_knowledge(self, handler):
        data = handler(self)
        if self.knowledge is None:
            data.pop("knowledge", None)
        return data


class Disclosure(AudienceRecord):
    origin: str | None = None
    message_id_boundary: int = Field(ge=0, strict=True)
    id: str = Field(default_factory=lambda: uuid.uuid4().hex, min_length=1)
    revision: int = Field(default=1, ge=1, strict=True)
    text: StrictStr = Field(min_length=1)
    acquired: Acquisition
    provenance: tuple[SourceReference, ...] = ()

    @field_validator("text")
    @classmethod
    def nonempty_text(cls, value):
        if not value.strip():
            raise ValueError("Disclosure text must be nonempty")
        return value


class SceneKnowledge(KnowledgeRecord):
    last_order: int = Field(default=0, ge=0, strict=True)
    disclosures: tuple[Disclosure, ...] = ()

    @model_validator(mode="after")
    def unique_disclosures(self):
        ids = [item.id for item in self.disclosures]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate disclosure ID")
        return self


class CharacterView(KnowledgeRecord):
    status: Literal["ready", "pending", "failed", "omitted", "unavailable"]
    text: str | None = None
    source: SourceReference | None = None
    acquired: Acquisition | None = None

    @model_validator(mode="after")
    def text_only_when_ready(self):
        if self.status == "ready" and (self.text is None or not self.text.strip()):
            raise ValueError("A ready character view requires text")
        if self.status != "ready" and self.text is not None:
            raise ValueError("Unavailable character content cannot contain text")
        return self


class PerspectiveInvalidation(KnowledgeRecord):
    source: SourceReference
    replacement: SourceReference | None
    affected: tuple[SourceReference, ...]
    reason: Literal["content", "views", "deleted", "rename"]
