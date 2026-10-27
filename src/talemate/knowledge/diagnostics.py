"""Bounded author-facing samples from context selectors."""

from collections import Counter
from textwrap import shorten

from pydantic import BaseModel, Field, PrivateAttr


class ContextDiagnostics(BaseModel):
    sample_limit: int = 20
    text_limit: int = 500
    counts: Counter = Field(default_factory=Counter)
    samples: list[dict] = Field(default_factory=list)
    _seen: set = PrivateAttr(default_factory=set)

    def exclude(self, kind, identity, text, reason, section="History", layer=None):
        key = kind, str(identity), layer, reason
        if key in self._seen:
            return
        self._seen.add(key)
        self.counts[reason] += 1
        if self.counts[reason] <= self.sample_limit:
            self.samples.append(
                {
                    "kind": kind,
                    "id": identity,
                    "layer": layer,
                    "text": shorten(str(text), width=self.text_limit, placeholder="…"),
                    "reason": reason,
                    "section": section,
                }
            )
