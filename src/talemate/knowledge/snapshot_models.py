from pydantic import Field, model_validator

from talemate.knowledge.perspective_models import KnowledgeRecord, PerspectiveOutput


class SnapshotPerspectives(KnowledgeRecord):
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    views: tuple[PerspectiveOutput, ...] = ()

    @model_validator(mode="after")
    def unambiguous_audiences(self):
        names = [name for view in self.views for name in view.audience]
        if len(names) != len(set(names)):
            raise ValueError("Overlapping snapshot audiences")
        return self
