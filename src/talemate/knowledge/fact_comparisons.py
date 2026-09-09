from collections import defaultdict

import numpy as np

from talemate.instance import get_agent
from talemate.knowledge.evidence import passage_spans, view_evidence, message_views
from talemate.knowledge.perspectives import PerspectiveReadContext
from talemate.knowledge.perspective_models import PassageEvidence


class FactComparisons:
    def __init__(self, scene, batches, *, read=None):
        self.read = read or PerspectiveReadContext(scene)
        self.texts = defaultdict(dict)
        self.vectors = {}
        self.scores = {}
        self.inputs = {}
        self.distances = {}
        for source, audience, parsed in batches:
            if not audience:
                continue
            evidence = {
                item.id: item
                for item in view_evidence(scene, source, audience[0], read=self.read)
            }
            references = tuple(
                reference
                for reference, _ in message_views(
                    scene, source, audience[0], read=self.read
                ).values()
            )
            self.inputs[source, audience[0]] = references
            for fact in parsed:
                if fact.evidence_id in evidence:
                    for reference in references:
                        self.texts[reference.id, reference.revision][
                            " ".join(fact.text.split())
                        ] = None
        source_keys = {source.key for source, _, _ in batches}
        for fact in scene.world_state.facts.values():
            for item in fact.contributions:
                if item.evidence is not None:
                    key = (item.evidence.message_id, item.evidence.revision)
                    if item.source.key in source_keys:
                        self.texts[key][item.text] = None

    async def passage(self, evidence):
        key = (evidence.message_id, evidence.revision)
        if key not in self.vectors:
            owner = self.read.sources[("message", evidence.message_id, 0)][0]
            spans = passage_spans(owner.text)
            texts = list(dict.fromkeys((*spans, *self.texts[key])))
            vectors = await get_agent("memory").embed_texts(texts)
            self.vectors[key] = (spans, dict(zip(texts, vectors)))
        return self.vectors[key]

    async def outranking(self, text, evidence, source, character):
        scores = {}
        for reference in self.inputs[source, character]:
            key = (text, reference.id, reference.revision)
            if key not in self.scores:
                spans, vectors = await self.passage(
                    PassageEvidence(
                        message_id=reference.id, revision=reference.revision, span=0
                    )
                )
                vector = vectors[text]
                self.scores[key] = {
                    PassageEvidence(
                        message_id=reference.id, revision=reference.revision, span=index
                    ): float(np.dot(vector, vectors[span]))
                    if np.any(vector) and np.any(vectors[span])
                    else float("nan")
                    for index, span in enumerate(spans)
                }
            scores.update(self.scores[key])
        cited = scores.get(evidence, float("nan"))
        if not np.isfinite(cited) or any(
            not np.isfinite(score) for score in scores.values()
        ):
            return None
        return tuple(item for item, score in scores.items() if score > cited)

    async def distance(self, evidence, left, right):
        key = (evidence.message_id, evidence.revision, *sorted((left, right)))
        if key not in self.distances:
            _, vectors = await self.passage(evidence)
            self.distances[key] = float(np.linalg.norm(vectors[left] - vectors[right]))
        return self.distances[key]
