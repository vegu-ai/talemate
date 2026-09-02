"""
Cross-encoder rerank for memory retrieval (opt-in).

The model is loaded on first use on the memory agent's device. A load
failure is recorded and every later call returns the candidates unchanged,
so retrieval never depends on the model being available.
"""

import structlog

__all__ = ["CrossEncoderReranker", "RERANK_MODEL", "RERANK_CANDIDATES", "RERANK_KEEP"]

log = structlog.get_logger("talemate.agents.memory.rerank")

RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
RERANK_CANDIDATES = 30
RERANK_KEEP = 5


class CrossEncoderReranker:
    def __init__(self, device: str = "cpu", model_name: str = RERANK_MODEL):
        self.device = device
        self.model_name = model_name
        self.model = None
        self.error: str | None = None

    @property
    def available(self) -> bool:
        return self.model is not None and self.error is None

    def load(self) -> bool:
        """Load the model once; a failure is final for this instance."""
        if self.model is not None or self.error is not None:
            return self.available
        try:
            from sentence_transformers import CrossEncoder

            self.model = CrossEncoder(self.model_name, device=self.device)
            log.info("rerank model loaded", model=self.model_name, device=self.device)
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            log.error(
                "rerank model failed to load",
                model=self.model_name,
                device=self.device,
                error=self.error,
            )
        return self.available

    def scores(self, queries: list[str], docs: list[str]) -> list[float]:
        """Best score of each document over the queries (query, document pairs)."""
        if not self.available or not docs or not queries:
            return []
        pairs = [(query, str(doc)) for doc in docs for query in queries]
        raw = self.model.predict(pairs)
        per_query = len(queries)
        return [
            max(float(s) for s in raw[i * per_query : (i + 1) * per_query])
            for i in range(len(docs))
        ]

    def rerank(self, queries: list[str], docs: list, keep: int = RERANK_KEEP) -> list:
        """The `keep` best documents by cross-encoder score, best first."""
        if not self.load():
            return docs
        scored = list(zip(self.scores(queries, docs), range(len(docs)), docs))
        if not scored:
            return docs
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [doc for _, _, doc in scored[:keep]]
