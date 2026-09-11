from __future__ import annotations

from typing import TYPE_CHECKING

import asyncio
import functools
import hashlib
import threading
import traceback
from contextlib import contextmanager
from contextvars import ContextVar
import numpy as np
from typing import Callable, Literal

import structlog
from chromadb.config import Settings

import talemate.events as events
from talemate.knowledge.presence import presence_metadata
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.topics import known_bucket
from talemate.knowledge.memory import audience_where
from talemate.agents.memory.audiences import AudienceMemoryMixin
import talemate.util as util
from talemate.client import ClientBase
import talemate.instance as instance
from talemate.agents.base import (
    Agent,
    AgentAction,
    AgentActionConfig,
    AgentActionNote,
    AgentDetail,
    set_processing,
)
from talemate.config.schema import EmbeddingFunctionPreset
from talemate.context import scene_is_loading, active_scene
from talemate.emit import emit
import talemate.emit.async_signals as async_signals
from talemate.agents.memory.context import memory_request, MemoryRequest
from talemate.agents.memory.exceptions import (
    EmbeddingsModelLoadError,
    SetDBError,
)
from talemate.agents.memory.schema import MemoryDocument
from talemate.knowledge.chronology import (
    fact_timestamp,
    memory_fact,
    ranked_facts,
    ranked_fact_documents,
    render_fact_document,
)

from talemate.agents.memory.rerank import (
    CrossEncoderReranker,
    RERANK_MODEL,
    RERANK_CANDIDATES,
    RERANK_KEEP,
)
from talemate.util.gpu import release_cuda_cache

import talemate.agents.memory.nodes  # noqa: F401

try:
    import chromadb
    import chromadb.errors
    from chromadb.utils import embedding_functions
except ImportError:
    chromadb = None
    pass

from talemate.agents.registry import register

if TYPE_CHECKING:
    from talemate.client.base import ClientEmbeddingsStatus

log = structlog.get_logger("talemate.agents.memory")

# how many of the nearest topic's facts join a query's results
TOPIC_FACTS_PER_QUERY = 3
OPENROUTER_EMBEDDINGS_BASE_URL = "https://openrouter.ai/api/v1"

HostedEmbeddingsProvider = Literal["OpenAI", "OpenRouter"]

_expected_write_scene = ContextVar("memory_expected_write_scene", default=None)


@contextmanager
def memory_write_scene(scene):
    """Fence a shared memory-agent write to the scene selected by its caller."""
    token = _expected_write_scene.set(scene)
    try:
        yield
    finally:
        _expected_write_scene.reset(token)


if not chromadb:
    log.info("ChromaDB not found, disabling Chroma agent")


class MemoryAgent(AudienceMemoryMixin, Agent):
    """
    An agent that can be used to maintain and access a memory of the world
    using vector databases
    """

    agent_type = "memory"
    verbose_name = "Memory"

    @classmethod
    def init_actions(cls, presets: list[dict] | None = None) -> dict[str, AgentAction]:
        if presets is None:
            presets = []

        actions = {
            "_config": AgentAction(
                enabled=True,
                label="Configure",
                description="Memory agent configuration",
                config={
                    "embeddings": AgentActionConfig(
                        type="text",
                        value="default",
                        label="Embeddings",
                        choices=presets,
                        description="Which embeddings to use",
                        scene_overridable=False,
                    ),
                    "device": AgentActionConfig(
                        type="text",
                        value="cpu",
                        label="Device",
                        description="Which device to use for embeddings (for local embeddings)",
                        note="Making changes to the embeddings or the device while a scene is loaded will cause the memory database to be re-imported. Depending on the size of the model and scene this may take a while.",
                        choices=[
                            {"value": "cpu", "label": "CPU"},
                            {"value": "cuda", "label": "CUDA"},
                        ],
                        scene_overridable=False,
                    ),
                },
            ),
            "topics": AgentAction(
                enabled=True,
                container=True,
                can_be_disabled=True,
                icon="mdi-shape-outline",
                label="Topics",
                description="Group recorded facts by subject to show each character's knowledge and find related memories. Turn on for the Known facts by topic table and topic-based memory retrieval; no extra text-generation request. Standard mode can also use the Conversation agent's Topic knowledge overview.",
                config={
                    "recluster_step": AgentActionConfig(
                        type="number",
                        label="Facts between topic updates",
                        description="Regroup topics when the fact count changes by this many. Lower for more frequent updates; raise to regroup less often. Editing, deleting or regenerating facts, or changing the embedding preset, updates topics immediately.",
                        value=20,
                        min=1,
                        max=200,
                        step=1,
                    ),
                    "similarity_threshold": AgentActionConfig(
                        type="number",
                        label="Topic similarity",
                        description="Set how closely facts must match to share a topic, and how closely a topic must match a memory search. Raise for tighter, smaller groups; lower for broader groups. Set to 0 to use the embedding preset.",
                        note_on_value={
                            0: AgentActionNote(
                                color="primary",
                                text="Use embedding preset: 0 uses its Topic Threshold instead of a custom value.",
                            ),
                        },
                        value=0,
                        min=0,
                        max=0.99,
                        step=0.01,
                    ),
                },
            ),
            "retrieval": AgentAction(
                enabled=True,
                container=True,
                icon="mdi-filter-variant",
                label="Retrieval",
                description="How similarity results are ranked and merged before they reach a prompt. Nothing in this group adds a request; the cross-encoder runs a local model.",
                config={
                    "recency_weight": AgentActionConfig(
                        type="number",
                        label="Recency weight",
                        description="Newer results rank higher: each result's score is its distance plus this weight times its age (0 = newest, 1 = oldest in the result set). 0 turns the term off.",
                        value=0.1,
                        min=0.0,
                        max=1.0,
                        step=0.05,
                    ),
                    "mmr_threshold": AgentActionConfig(
                        type="number",
                        label="Diversity threshold",
                        description="A result whose embedding is more similar than this (cosine) to one already selected is skipped. 1 turns the check off.",
                        value=0.92,
                        min=0.5,
                        max=1.0,
                        step=0.01,
                    ),
                    "entity_lookup": AgentActionConfig(
                        type="bool",
                        label="Entity lookup",
                        description="When the recent lines name a character who is not in the scene (a name with a capital must appear as written), fetch that character's description from the memory store and add it ahead of the similarity results.",
                        value=True,
                    ),
                    "similarity_gate": AgentActionConfig(
                        type="bool",
                        label="Match known facts",
                        description="Allow a memory of an event the character missed when it closely matches a fact they know. Turn on to recognize retold information; turn off for stricter access filtering. Uses the Summarizer's Fact matching tolerance and cannot override entry visibility or blocked knowledge.",
                        value=True,
                    ),
                    "rerank": AgentActionConfig(
                        type="bool",
                        label="Cross-encoder rerank",
                        description=f"Score the top {RERANK_CANDIDATES} merged results against the queries with a local cross-encoder and keep the best {RERANK_KEEP}. No request; the model runs on the embeddings device.",
                        note=f"Downloads {RERANK_MODEL} on first use. When the model fails to load, retrieval carries on without the rerank and the agent shows the error.",
                        value=False,
                    ),
                },
            ),
        }
        return actions

    def __init__(self, **kwargs):
        self.db = None
        self.init_audience_index()
        self.memory_tracker = {}
        self._ready_to_add = False
        self._db_generation = 0
        self._db_lock = threading.Lock()
        self._reranker: CrossEncoderReranker | None = None
        # topic centroids (unit vectors) by topic id; rebuilt on load
        self.topic_centroids: dict[str, np.ndarray] = {}

        async_signals.get("config.changed").connect(self.on_config_changed)

        async_signals.get("client.embeddings_available").connect(
            self.on_client_embeddings_available
        )

        self.actions = MemoryAgent.init_actions(presets=self.get_presets)

    @property
    def readonly(self):
        memory_never_persisted = getattr(self.scene, "_memory_never_persisted", False)
        scene_immutable_save = getattr(self.scene, "immutable_save", False)

        if (
            scene_is_loading.get()
            and not memory_never_persisted
            and not scene_immutable_save
        ):
            return True

        return False

    @property
    def db_name(self):
        raise NotImplementedError()

    @property
    def get_presets(self):
        def _label(embedding: EmbeddingFunctionPreset):
            prefix = embedding.client if embedding.client else embedding.embeddings
            if embedding.model:
                return f"{prefix}: {embedding.model}"
            else:
                return f"{prefix}"

        return [
            {"value": k, "label": _label(v)}
            for k, v in self.config.presets.embeddings.items()
        ]

    @property
    def embeddings_config(self):
        _embeddings = self.actions["_config"].config["embeddings"].value
        return self.config.presets.embeddings.get(_embeddings)

    @property
    def embeddings(self):
        try:
            return self.embeddings_config.embeddings
        except AttributeError:
            return None

    @property
    def using_openai_embeddings(self):
        return self.embeddings == "openai"

    @property
    def using_openrouter_embeddings(self):
        return self.embeddings == "openrouter"

    @property
    def using_sentence_transformer_embeddings(self):
        return self.embeddings == "default" or self.embeddings == "sentence-transformer"

    @property
    def using_client_api_embeddings(self):
        return self.embeddings == "client-api"

    @property
    def using_local_embeddings(self):
        return self.embeddings in ["sentence-transformer", "default"]

    @property
    def embeddings_client(self):
        try:
            return self.embeddings_config.client
        except AttributeError:
            return None

    @property
    def max_distance(self) -> float:
        distance = float(self.embeddings_config.distance)
        distance_mod = float(self.embeddings_config.distance_mod)

        return distance * distance_mod

    @property
    def model(self):
        try:
            return self.embeddings_config.model
        except AttributeError:
            return None

    @property
    def distance_function(self):
        try:
            return self.embeddings_config.distance_function
        except AttributeError:
            return None

    @property
    def device(self) -> str:
        return self.actions["_config"].config["device"].value

    @property
    def trust_remote_code(self) -> bool:
        try:
            return self.embeddings_config.trust_remote_code
        except AttributeError:
            return False

    @property
    def retrieval_recency_weight(self) -> float:
        return float(self.resolve_config("retrieval", "recency_weight"))

    @property
    def retrieval_mmr_threshold(self) -> float:
        return float(self.resolve_config("retrieval", "mmr_threshold"))

    @property
    def retrieval_entity_lookup(self) -> bool:
        return bool(self.resolve_config("retrieval", "entity_lookup"))

    @property
    def sanitized_action_config(self):
        config = super().sanitized_action_config
        if (
            character_knowledge_enabled(getattr(self, "scene", None))
            and "retrieval" in config
        ):
            config["retrieval"]["config"].pop("similarity_gate", None)
        return config

    @property
    def retrieval_similarity_gate(self) -> bool:
        return bool(self.resolve_config("retrieval", "similarity_gate"))

    @property
    def retrieval_rerank(self) -> bool:
        return bool(self.resolve_config("retrieval", "rerank"))

    # topics

    @property
    def topics_enabled(self) -> bool:
        return self.resolve_enabled("topics")

    @property
    def topics_recluster_step(self) -> int:
        return int(self.resolve_config("topics", "recluster_step"))

    @property
    def topics_similarity_threshold(self) -> float:
        """The Topics setting when set (> 0), else the embedding preset's model-dependent value."""
        value = float(self.resolve_config("topics", "similarity_threshold") or 0)
        if value > 0:
            return value
        preset = self.embeddings_config
        if preset is None:
            return 0.5
        return float(preset.topic_threshold)

    async def rebuild_topic_centroids(self, scene):
        """Centroids from the stored fact vectors of every topic's members."""
        topics = scene.world_state.topics
        ids = [i for topic in topics.values() for i in topic.fact_ids]
        centroids: dict[str, np.ndarray] = {}
        if ids and self.ready:
            vectors = await self.get_embeddings(ids)
            for topic in topics.values():
                members = [vectors[i] for i in topic.fact_ids if i in vectors]
                if not members:
                    continue
                units = []
                for vector in members:
                    vector = np.asarray(vector, dtype=float)
                    norm = np.linalg.norm(vector)
                    units.append(vector / norm if norm > 0 else vector)
                centroid = np.mean(np.stack(units), axis=0)
                norm = np.linalg.norm(centroid)
                centroids[topic.id] = centroid / norm if norm > 0 else centroid
        self.topic_centroids = centroids
        return centroids

    async def embed_text(self, text: str) -> np.ndarray | None:
        """The query embedding, or None when no embedding function is set."""
        try:
            embed_fn = self.embedding_function
        except RuntimeError:
            return None
        vectors = await asyncio.to_thread(embed_fn, [text])
        if vectors is None or len(vectors) == 0:
            return None
        vector = np.asarray(vectors[0], dtype=float)
        norm = np.linalg.norm(vector)
        return vector / norm if norm > 0 else vector

    def nearest_topic(self, vector: np.ndarray) -> str | None:
        """The topic whose centroid is closest to the vector, at or above the threshold."""
        if not self.topic_centroids or vector is None:
            return None
        best_id, best = None, self.topics_similarity_threshold
        for topic_id, centroid in self.topic_centroids.items():
            score = float(np.dot(vector, centroid))
            if score >= best:
                best_id, best = topic_id, score
        return best_id

    async def _topic_first(
        self, query: str, accepted: list, filter, *, viewer=None, ranking_viewer=None
    ) -> list:
        """
        The nearest topic's highest-scoring eligible facts that the similarity search
        did not return, ahead of that query's results.
        """
        if viewer is not None:
            return await self._audience_topic_first(query, accepted, filter, viewer)
        if not self.topics_enabled or not self.topic_centroids or not self.scene:
            return []
        topic_id = self.nearest_topic(await self.embed_text(query))
        if topic_id is None:
            return []
        topic = self.scene.world_state.topics.get(topic_id)
        if topic is None:
            return []
        facts = self.scene.world_state.facts
        seen = {getattr(doc, "id", None) for doc in accepted}
        from talemate.knowledge.revision_browsing import fact_current

        candidates = {
            i: facts[i]
            for i in topic.fact_ids
            if i in facts and i not in seen and fact_current(self.scene, facts[i])
        }
        visible = (
            {fact.id: fact for fact in known_bucket(self.scene, ranking_viewer)}
            if ranking_viewer is not None
            and any(fact.supersedes for fact in candidates.values())
            else None
        )
        predecessors = {
            identity: fact
            for identity, fact in candidates.items()
            if visible is None or identity in visible
        }
        members = ranked_facts(
            self.scene,
            candidates.values(),
            character=ranking_viewer,
            superseders=visible.values() if visible is not None else None,
            predecessors=predecessors,
        )
        selected = {f.id: f for f in members[:TOPIC_FACTS_PER_QUERY]}
        ids = list(selected)
        log.debug("topic first matched", topic=topic_id, candidates=ids)
        if not ids:
            return []
        documents = await self.get_document(ids)
        found = [documents[i] for i in ids if i in documents]
        if filter is not None:
            found = [doc for doc in found if filter(doc)]
        log.debug("topic first", topic=topic_id, added=[d.id for d in found])
        return [
            render_fact_document(
                self.scene,
                doc,
                fact=selected[doc.id],
                predecessor=predecessors.get(selected[doc.id].supersedes),
            )
            for doc in found
        ]

    @staticmethod
    def _audience_topic_groups(topics, documents, vectors, filter=None):
        by_source = {}
        for doc in documents.values():
            if doc.id in vectors and (filter is None or filter(doc)):
                by_source.setdefault(doc.meta["knowledge_id"], []).append(doc)
        groups = []
        for topic in topics.values():
            candidates = [
                doc
                for identity in topic.fact_ids
                for doc in by_source.get(identity, ())
            ]
            units = []
            for doc in candidates:
                vector = np.asarray(vectors[doc.id], dtype=float)
                norm = np.linalg.norm(vector)
                if norm:
                    units.append(vector / norm)
            if not units:
                continue
            centroid = np.mean(units, axis=0)
            norm = np.linalg.norm(centroid)
            if not norm:
                continue
            candidates.sort(
                key=lambda doc: (
                    -doc.meta.get("restatements", 0),
                    -doc.meta.get("ts", 0),
                )
            )
            groups.append((centroid / norm, candidates))
        return groups

    async def _audience_topic_first(self, query, accepted, filter, viewer):
        if not self.topics_enabled or not self.scene.world_state.topics:
            return []
        scene = self.scene
        await self.ensure_audience_index(scene)
        state = self._audience_state(scene)
        topics = scene.world_state.topics
        key = (
            state.collection_revision,
            state.revision,
            tuple(
                (identity, tuple(topic.fact_ids)) for identity, topic in topics.items()
            ),
        )
        cached = state.topics.get(viewer)
        if cached is None or cached[0] != key:
            documents = await self.get_documents_by_meta({"typ": "fact"}, viewer=viewer)
            # Cache source text; relative ages must be rendered against the current time.
            documents = {
                identity: MemoryDocument(doc.raw, doc.meta, doc.id, doc.raw)
                for identity, doc in documents.items()
            }
            vectors = await self.get_embeddings(list(documents)) if documents else {}
            groups = self._audience_topic_groups(topics, documents, vectors)
            cached = (key, documents, vectors, groups)
            # An outer audience_operation retries if this build raced an edit.
            if (state.collection_revision, state.revision) == key[:2]:
                state.topics[viewer] = cached
        _, documents, vectors, groups = cached
        if filter is not None:
            # Arbitrary caller filters may change independently of index state.
            # Reuse the fetched variants/vectors, but narrow before topic selection.
            current_documents = {
                identity: self._dated_document(doc.raw, doc.meta, doc.id)
                for identity, doc in documents.items()
            }
            groups = self._audience_topic_groups(
                topics, current_documents, vectors, filter
            )
        query_vector = await self.embed_text(query)
        if query_vector is None:
            return []
        best, members = self.topics_similarity_threshold, []
        for centroid, candidates in groups:
            score = float(np.dot(query_vector, centroid))
            if score >= best:
                best, members = score, candidates
        seen = {doc.id for doc in accepted}
        selected = ranked_fact_documents(
            scene, [doc for doc in members if doc.id not in seen], character=viewer
        )[:TOPIC_FACTS_PER_QUERY]
        return selected

    @property
    def reranker(self) -> CrossEncoderReranker:
        """The cross-encoder for the current device, created on first access."""
        if self._reranker is None or self._reranker.device != self.device:
            self._reranker = CrossEncoderReranker(device=self.device)
        return self._reranker

    @property
    def rerank_error(self) -> str | None:
        return self._reranker.error if self._reranker else None

    @property
    def fingerprint(self) -> str:
        """
        Returns a unique fingerprint for the current configuration
        """

        model_name = self.model.replace("/", "-") if self.model else "none"

        return f"{self.embeddings}-{model_name}-{self.distance_function}-{self.device}-{self.trust_remote_code}".lower()

    async def apply_config(self, *args, **kwargs):
        _fingerprint = self.fingerprint

        await super().apply_config(*args, **kwargs)

        fingerprint_changed = _fingerprint != self.fingerprint

        # have embeddings or device changed?
        if fingerprint_changed:
            log.warning(
                "memory agent",
                status="embedding function changed",
                old=_fingerprint,
                new=self.fingerprint,
            )
            await self.handle_embeddings_change()

    @set_processing
    async def handle_embeddings_change(self):
        scene = active_scene.get()

        # if sentence-transformer and no model-name, set embeddings to default
        if self.using_sentence_transformer_embeddings and not self.model:
            self.actions["_config"].config["embeddings"].value = "default"

        if not scene or not scene.active:
            return

        self.close_db(scene)
        emit("status", "Re-importing context database", status="busy")
        # topics were grouped in the old vector space: rebuilt on import
        scene.world_state.topics = {}
        scene.world_state.topics_fact_count = 0
        self.topic_centroids = {}
        await scene.commit_to_memory()
        if not scene.immutable_save:
            await scene.save(auto=True)
        emit("status", "Context database re-imported", status="success")

    def sync_presets(self) -> list[dict]:
        self.actions["_config"].config["embeddings"].choices = self.get_presets
        return self.actions["_config"].config["embeddings"].choices

    async def fix_broken_embeddings(self):
        if not self.embeddings_config:
            self.actions["_config"].config["embeddings"].value = "default"
            await self.emit_status()
            await self.handle_embeddings_change()
            await self.save_config()

    async def on_config_changed(self, event):
        loop = asyncio.get_running_loop()
        openai_key = self.openai_api_key

        fingerprint = self.fingerprint

        old_presets = self.actions["_config"].config["embeddings"].choices.copy()

        new_presets = self.sync_presets()
        if fingerprint != self.fingerprint:
            log.warning(
                "memory agent",
                status="embedding function changed",
                old=fingerprint,
                new=self.fingerprint,
            )
            loop.run_until_complete(self.handle_embeddings_change())

        emit_status = False

        if openai_key != self.openai_api_key:
            emit_status = True

        if old_presets != new_presets:
            emit_status = True

        if emit_status:
            loop.run_until_complete(self.emit_status())

        await self.fix_broken_embeddings()

    async def on_client_embeddings_available(self, event: "ClientEmbeddingsStatus"):
        current_embeddings = self.actions["_config"].config["embeddings"].value

        if current_embeddings == event.client.embeddings_identifier:
            event.seen = True
            return

        if not self.using_client_api_embeddings or not self.ready:
            log.warning(
                "memory agent - client embeddings available",
                status="changing embeddings",
                old=current_embeddings,
                new=event.client.embeddings_identifier,
            )
            self.actions["_config"].config[
                "embeddings"
            ].value = event.client.embeddings_identifier
            await self.emit_status()
            await self.handle_embeddings_change()
            await self.save_config()
            event.seen = True

    @set_processing
    async def set_db(self):
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._set_db)
            self.invalidate_audience_index(reconcile=True)
        except EmbeddingsModelLoadError:
            raise
        except Exception as e:
            log.error(
                "memory agent", error="failed to set db", details=traceback.format_exc()
            )

            if "torchvision::nms does not exist" in str(e):
                raise SetDBError(
                    "The embeddings you are trying to use require the `torchvision` package to be installed"
                )

            raise SetDBError(str(e))

    def close_db(self):
        raise NotImplementedError()

    async def count(self):
        raise NotImplementedError()

    async def _wait_until_ready(self) -> bool:
        """
        Wait for the db to become writable.

        Returns False when the agent was rebound to another scene while waiting -
        the write belongs to a scene that is gone, and writing it once the next
        scene installs its db would put it in the wrong collection.
        """
        scene = self.scene

        while not self._ready_to_add:
            if self.scene is not scene:
                break
            await asyncio.sleep(0.1)

        if self.scene is not scene:
            log.debug("memory agent", status="scene released while waiting for db")
            return False

        return True

    def _write_memory(self, scene, operation, *args, **kwargs):
        # Executor queues and retries can outlive the scene that requested the write.
        if self.scene is not scene:
            return False
        with self._db_lock:
            # A source digest cannot see a write that has started but not landed.
            scene.memory_writes_in_flight += 1
            scene.memory_revision += 1
        try:
            operation(*args, **kwargs)
            return True
        finally:
            # The executor can finish a write after its awaiting task is cancelled.
            with self._db_lock:
                scene.memory_revision += 1
                scene.memory_writes_in_flight -= 1

    @set_processing
    async def add(self, text, character=None, uid=None, ts: int = None, **kwargs):
        scene = _expected_write_scene.get() or self.scene
        if self.scene is not scene:
            return False
        if not text:
            return False
        if self.readonly:
            log.debug("memory agent", status="readonly")
            return False

        if not await self._wait_until_ready():
            return False
        if self.scene is not scene:
            return False

        log.debug(
            "memory agent add",
            text=text[:50],
            character=character,
            uid=uid,
            ts=ts,
            **kwargs,
        )

        loop = asyncio.get_running_loop()
        attempted = False

        try:
            completed = await loop.run_in_executor(
                None,
                functools.partial(
                    self._write_memory,
                    scene,
                    self._add,
                    text,
                    character,
                    uid=uid,
                    ts=ts,
                    **kwargs,
                ),
            )
        except AttributeError as e:
            attempted = True
            # not sure how this sometimes happens.
            # chromadb model None
            # race condition because we are forcing async context onto it?

            log.error(
                "memory agent",
                error="failed to add memory",
                details=e,
                text=text[:50],
                character=character,
                uid=uid,
                ts=ts,
                **kwargs,
            )
            await asyncio.sleep(1.0)
            try:
                completed = await loop.run_in_executor(
                    None,
                    functools.partial(
                        self._write_memory,
                        scene,
                        self._add,
                        text,
                        character,
                        uid=uid,
                        ts=ts,
                        **kwargs,
                    ),
                )
            except Exception as e:
                log.error(
                    "memory agent",
                    error="failed to add memory (retried)",
                    details=e,
                    text=text[:50],
                    character=character,
                    uid=uid,
                    ts=ts,
                    **kwargs,
                )
                completed = False

        if completed or attempted:
            self.invalidate_audience_writes([{"id": uid, "meta": kwargs}], scene=scene)
        return completed

    def _add(self, text, character=None, ts: int = None, **kwargs):
        raise NotImplementedError()

    @set_processing
    async def add_many(self, objects: list[dict]):
        """An empty batch refreshes authored audiences without a store write."""
        scene = _expected_write_scene.get() or self.scene
        if self.scene is not scene:
            return False
        if self.readonly:
            log.debug("memory agent", status="readonly")
            return False
        if not objects:
            self.invalidate_audience_writes(objects, scene=scene)
            return True

        if not await self._wait_until_ready():
            return False
        if self.scene is not scene:
            return False

        log.debug("memory agent add many", len=len(objects))

        loop = asyncio.get_running_loop()
        operation = loop.run_in_executor(
            None,
            functools.partial(self._write_memory, scene, self._add_many, objects),
        )
        return await self._shielded_write(
            operation,
            functools.partial(self.invalidate_audience_writes, objects, scene=scene),
        )

    async def _shielded_write(self, operation, invalidate):
        try:
            completed = await asyncio.shield(operation)
        except asyncio.CancelledError:
            if operation.done():
                self._complete_cancelled_write(invalidate, operation)
            else:
                operation.add_done_callback(
                    functools.partial(self._complete_cancelled_write, invalidate)
                )
            raise
        except BaseException:
            invalidate()
            raise
        if completed:
            invalidate()
        return completed

    def _complete_cancelled_write(self, invalidate, operation):
        if operation.cancelled() is True:
            return
        error = operation.exception()
        if error is not None:
            log.warning("memory write failed after cancellation", error=str(error))
            invalidate()
        elif operation.result():
            invalidate()

    def _add_many(self, objects: list[dict]):
        """
        Add multiple objects to the memory
        """
        raise NotImplementedError()

    @set_processing
    async def delete(self, meta: dict):
        """
        Delete an object from the memory
        """
        scene = _expected_write_scene.get() or self.scene
        if self.scene is not scene:
            return False
        if self.readonly:
            log.debug("memory agent", status="readonly")
            return False

        if not await self._wait_until_ready():
            return False
        if self.scene is not scene:
            return False

        loop = asyncio.get_running_loop()
        operation = loop.run_in_executor(
            None, functools.partial(self._write_memory, scene, self._delete, meta)
        )
        return await self._shielded_write(
            operation,
            functools.partial(
                self.invalidate_audience_index, scene=scene, reconcile=True
            ),
        )

    def _delete(self, meta: dict):
        """
        Delete an object from the memory
        """
        raise NotImplementedError()

    @set_processing
    async def get(self, text, character=None, *, viewer=None, **query):
        with MemoryRequest(query=text, query_params=query) as active_memory_request:
            active_memory_request.max_distance = self.max_distance
            if viewer is not None:
                return await self.audience_query(text, character, viewer, query)
            if character_knowledge_enabled(self.scene):
                await self.prepare_author_index()
            return await asyncio.to_thread(self._get, text, character, **query)
            # return await loop.run_in_executor(
            #    None, functools.partial(self._get, text, character, **query)
            # )

    def _get(self, text, character=None, **query):
        raise NotImplementedError()

    @set_processing
    async def get_document(self, id, *, viewer=None):
        if viewer is not None:
            self.validate_audience_viewer(viewer)
            ids = [id] if isinstance(id, str) else id
            return (
                await self.get_documents_by_meta(
                    {"knowledge_id": {"$in": [str(identity) for identity in ids]}},
                    viewer=viewer,
                )
                if ids
                else {}
            )
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._get_document, id)

    def _get_document(self, id):
        raise NotImplementedError()

    async def get_documents_by_meta(self, meta: dict, *, viewer=None) -> dict:
        """Documents whose metadata carries every given key/value, by id."""
        if viewer is not None:
            return await self.audience_read(
                self._get_documents_by_meta, meta, viewer=viewer
            )
        if not meta or not self.db:
            return {}
        await self.prepare_author_index()
        if not self.db:
            return {}
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._get_documents_by_meta, meta)

    def _get_documents_by_meta(self, meta: dict) -> dict:
        raise NotImplementedError()

    async def get_embeddings(self, ids: list[str]) -> dict[str, list[float]]:
        """
        Stored embedding vectors by document id (missing ids are absent).

        A read path: like `get` and `get_document` it never waits for the
        write gate, and an unset store answers with nothing.
        """
        if not ids or not self.db:
            return {}
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._get_embeddings, ids)

    def _get_embeddings(self, ids: list[str]) -> dict[str, list[float]]:
        raise NotImplementedError()

    async def near_duplicates(
        self, ids: list[str], against: list[str], max_distance: float
    ) -> set[str]:
        """
        The ids among `ids` whose stored embedding sits within `max_distance`
        (euclidean) of any stored embedding among `against`. One fetch and one
        distance matrix; an id without a stored vector is never a duplicate.
        """
        ids = [i for i in ids if i]
        against = [i for i in against if i]
        if not ids or not against:
            return set()
        vectors = await self.get_embeddings(list(dict.fromkeys(ids + against)))
        return self._near_duplicates_in(
            ids, {i: vectors[i] for i in against if i in vectors}, vectors, max_distance
        )

    async def near_duplicates_against(
        self, ids: list[str], anchors: dict[str, list[float]], max_distance: float
    ) -> set[str]:
        """Like `near_duplicates`, with the anchor vectors already in hand."""
        ids = [i for i in ids if i]
        if not ids or not anchors:
            return set()
        vectors = await self.get_embeddings(ids)
        return self._near_duplicates_in(ids, anchors, vectors, max_distance)

    @staticmethod
    def _near_duplicates_in(
        ids: list[str],
        anchors: dict[str, list[float]],
        vectors: dict[str, list[float]],
        max_distance: float,
    ) -> set[str]:
        rows = [i for i in ids if i in vectors]
        cols = list(anchors)
        if not rows or not cols:
            return set()
        vecs_a = np.asarray([vectors[i] for i in rows], dtype=float)
        vecs_b = np.asarray([anchors[i] for i in cols], dtype=float)
        norms_a = np.linalg.norm(vecs_a, axis=1, keepdims=True)
        norms_b = np.linalg.norm(vecs_b, axis=1, keepdims=True)
        vecs_a = np.divide(
            vecs_a, norms_a, out=np.zeros_like(vecs_a), where=norms_a != 0
        )
        vecs_b = np.divide(
            vecs_b, norms_b, out=np.zeros_like(vecs_b), where=norms_b != 0
        )
        a_squared = np.sum(vecs_a**2, axis=1).reshape(-1, 1)
        b_squared = np.sum(vecs_b**2, axis=1).reshape(1, -1)
        distances = np.sqrt(
            np.maximum(a_squared + b_squared - 2 * np.dot(vecs_a, vecs_b.T), 0.0)
        )
        nearest = distances.min(axis=1)
        return {rows[i] for i in range(len(rows)) if nearest[i] <= max_distance}

    async def on_archive_add(self, event: events.ArchiveEvent):
        await self.add(
            event.text,
            uid=event.memory_id,
            ts=event.ts,
            typ="history",
            **presence_metadata(event.present),
        )

    def connect(self, scene):
        super().connect(scene)
        async_signals.get("archive_add").connect(self.on_archive_add)

    async def memory_context(
        self,
        name: str,
        query: str,
        max_tokens: int = 1000,
        filter: Callable = lambda x: True,
    ):
        """
        Get the character memory context for a given character
        """

        memory_context = []

        if not query:
            return memory_context

        for memory in await self.get(
            query,
            **({"viewer": name} if character_knowledge_enabled(self.scene) else {}),
        ):
            if memory in memory_context:
                continue

            if filter and not filter(memory):
                continue

            memory_context.append(memory)

            if util.count_tokens(memory_context) >= max_tokens:
                break
        return memory_context

    @set_processing
    async def query(
        self,
        query: str,
        max_tokens: int = 1000,
        filter: Callable | None = None,
        **where,
    ) -> str | None:
        """
        Get the character memory context for a given character
        """

        try:
            return (
                await self.multi_query(
                    [query], max_tokens=max_tokens, filter=filter, **where
                )
            )[0]
        except IndexError:
            return None

    @set_processing
    async def multi_query(
        self,
        queries: list[str],
        iterate: int = 1,
        max_tokens: int = 1000,
        filter: Callable | None = None,
        formatter: Callable = lambda x: x,
        limit: int = 10,
        return_docs: bool = False,
        over_fetch: int = 1,
        topic_first: bool = False,
        viewer: str | None = None,
        ranking_viewer: str | None = None,
        **where,
    ):
        async def retrieve(_collection=None):
            return await self._multi_query(
                queries,
                iterate=iterate,
                max_tokens=max_tokens,
                filter=filter,
                formatter=formatter,
                limit=limit,
                return_docs=return_docs,
                over_fetch=over_fetch,
                topic_first=topic_first,
                viewer=viewer,
                ranking_viewer=ranking_viewer,
                **where,
            )

        if viewer is not None:
            return await self.audience_operation(viewer, retrieve)
        return await retrieve()

    async def _multi_query(
        self,
        queries: list[str],
        iterate: int = 1,
        max_tokens: int = 1000,
        filter: Callable | None = None,
        formatter: Callable = lambda x: x,
        limit: int = 10,
        return_docs: bool = False,
        over_fetch: int = 1,
        topic_first: bool = False,
        viewer: str | None = None,
        ranking_viewer: str | None = None,
        **where,
    ):
        """
        Get the character memory context for a given character

        `over_fetch` widens the vector search (limit × over_fetch) for callers
        whose filter drops many candidates. `topic_first` lets the nearest
        topic contribute its highest-scoring eligible facts (prompt retrieval only; a
        metadata condition in `where` turns it off).

        Per query the candidates pass the filter (and the similarity knowledge
        gate), are re-ranked by distance plus the recency term, and are cut
        to `iterate`. The per-query lists are merged round-robin, skipping
        near-identical results (diversity threshold), optionally reranked by
        the cross-encoder, and cut to the token budget.
        """

        ranking_viewer = viewer if ranking_viewer is None else ranking_viewer
        limit = limit * max(1, over_fetch)

        # First, collect results for each individual query (respecting the
        # per-query `iterate` limit) so that we have them available before we
        # start filling the final context. This prevents early queries from
        # monopolising the token budget.

        per_query_results: list[list[str]] = []
        # D23: perception access is decided by the backend audience condition;
        # even a caller-supplied bucket filter can only narrow that eligible set.
        gate_distance = (
            self._similarity_gate_distance()
            if filter and not character_knowledge_enabled(self.scene)
            else None
        )
        # the gate's anchors (the character's known facts and their vectors)
        # do not change between the queries of one call: fetched once
        anchors = await self._gate_anchors(filter) if gate_distance is not None else {}

        for query in queries:
            # Skip empty queries so that we keep indexing consistent for the
            # round-robin step that follows.
            if not query:
                per_query_results.append([])
                continue

            # Fetch potential memories for this query.
            raw_results = await self.get(
                formatter(query),
                limit=limit,
                **({"viewer": viewer} if viewer is not None else {}),
                **where,
            )

            accepted = await self._apply_filter(
                raw_results, filter, gate_distance, anchors
            )
            accepted = ranked_fact_documents(
                self.scene, self._rank_by_recency(accepted), character=ranking_viewer
            )
            # only a caller without a metadata condition asks for topic-first
            # facts: `where` is not applied to a fetch by id
            topic_docs = (
                await self._topic_first(
                    formatter(query),
                    accepted,
                    filter,
                    ranking_viewer=ranking_viewer,
                    **({"viewer": viewer} if viewer is not None else {}),
                )
                if topic_first and not where
                else []
            )
            per_query_results.append(
                (topic_docs + accepted)[: iterate + len(topic_docs)]
            )

        # a reranker that already failed to load is not asked again: the
        # plain, token-budgeted merge is the answer then
        rerank = (
            self.retrieval_rerank
            and bool([q for q in queries if q])
            and not self.reranker.error
        )
        merged = self._merge_round_robin(per_query_results)
        merged = ranked_fact_documents(self.scene, merged, character=ranking_viewer)

        if rerank:
            reranked = await self.rerank(
                [q for q in queries if q], merged[:RERANK_CANDIDATES]
            )
            if self.reranker.error:
                # A failed reranker keeps the filtered relevance order.
                return self._cut_to_budget(merged, max_tokens)
            merged = ranked_fact_documents(
                self.scene, reranked, character=ranking_viewer
            )

        return self._cut_to_budget(merged, max_tokens)

    def _similarity_gate_distance(self) -> float | None:
        """The near-duplicate distance the gate uses, or None when it is off."""
        if not self.retrieval_similarity_gate:
            return None
        return float(instance.get_agent("summarizer").archive_fact_dedupe_distance)

    async def _gate_anchors(self, filter: Callable | None) -> dict[str, list[float]]:
        """The stored vectors of the facts in the filter's bucket, by id."""
        known_fact_ids = getattr(filter, "known_fact_ids", None)
        if known_fact_ids is None:
            return {}
        ids = known_fact_ids()
        return await self.get_embeddings(ids) if ids else {}

    async def _apply_filter(
        self,
        raw_results: list,
        filter: Callable | None,
        gate_distance: float | None,
        anchors: dict[str, list[float]] | None = None,
    ) -> list:
        """
        The knowledge filter, then the similarity knowledge gate: a result
        rejected for presence alone passes when a fact in the character's
        bucket is a near-duplicate of it (its vector against the anchors).
        Admission does not exempt a result from duplicates in the final merge.
        """
        if not filter:
            return list(raw_results)

        accepted = []
        rejected = []
        for memory in raw_results:
            if filter(memory):
                accepted.append(memory)
            else:
                rejected.append(memory)

        if gate_distance is None or not rejected or not anchors:
            return accepted

        gateable = getattr(filter, "gateable", None)
        if gateable is None:
            return accepted

        candidates = [doc for doc in rejected if gateable(doc)]
        if not candidates:
            return accepted

        retold = await self.near_duplicates_against(
            [doc.id for doc in candidates], anchors, gate_distance
        )
        passed = []
        for doc in candidates:
            if doc.id in retold:
                passed.append(doc)
                log.debug("similarity gate passed", id=doc.id)

        if not passed:
            return accepted

        # keep the store's distance order across the two groups
        order = {id(doc): i for i, doc in enumerate(raw_results)}
        return sorted(accepted + passed, key=lambda doc: order.get(id(doc), 0))

    def _rank_by_recency(self, docs: list) -> list:
        """Stable re-rank by distance + recency_weight × normalised age."""
        weight = self.retrieval_recency_weight
        scene_ts = self.scene.ts if self.scene else None
        if weight <= 0 or scene_ts is None or len(docs) < 2:
            return list(docs)

        ages: list[int | None] = []
        for doc in docs:
            ts = (getattr(doc, "meta", None) or {}).get("ts")
            try:
                ages.append(None if ts is None else int(scene_ts) - util.coerce_ts(ts))
            except (TypeError, ValueError):
                ages.append(None)

        known = [age for age in ages if age is not None]
        if not known:
            return list(docs)
        span = max(1, max(known))

        def score(item):
            index, doc = item
            age = ages[index]
            age_norm = 0.5 if age is None else min(1.0, max(0.0, age / span))
            distance = doc.distance if doc.distance is not None else 0.0
            return (float(distance) + weight * age_norm, index)

        return [doc for _, doc in sorted(enumerate(docs), key=score)]

    def _is_fresher_fact(self, candidate, selected) -> bool:
        candidate_fact = memory_fact(self.scene, candidate)
        selected_fact = memory_fact(self.scene, selected)
        if candidate_fact is None or selected_fact is None:
            return False
        candidate_ts = fact_timestamp(candidate_fact)
        selected_ts = fact_timestamp(selected_fact)
        return (
            candidate_ts is not None
            and selected_ts is not None
            and candidate_ts > selected_ts
        )

    def _merge_round_robin(self, per_query_results: list[list]) -> list:
        threshold = self.retrieval_mmr_threshold
        memory_context: list = []
        selected_vectors: dict = {}
        idx = 0
        while True:
            # a skipped result (duplicate, near-identical) still counts as
            # progress: the lists are exhausted only when no list has an
            # item at this depth
            progressed = False

            for result_list in per_query_results:
                if idx >= len(result_list):
                    # No more items remaining for this query at this depth.
                    continue

                progressed = True
                memory = result_list[idx]

                # Avoid duplicates in the final context.
                if memory in memory_context:
                    continue

                vector = getattr(memory, "embedding", None)
                if vector is not None and threshold < 1.0:
                    vector = np.asarray(vector, dtype=float)
                    norm = np.linalg.norm(vector)
                    if norm > 0:
                        unit = vector / norm
                        duplicates = [
                            position
                            for position, other in selected_vectors.items()
                            if float(np.dot(unit, other)) > threshold
                        ]
                        replacement = (
                            min(duplicates)
                            if duplicates
                            and all(
                                self._is_fresher_fact(memory, memory_context[position])
                                for position in duplicates
                            )
                            else None
                        )
                        if replacement is not None:
                            # Preserve the selected fact's relevance slot before the budget cut.
                            for position in duplicates:
                                log.debug(
                                    "diversity skip",
                                    id=getattr(memory_context[position], "id", None),
                                    reason="duplicate",
                                    replacement_id=getattr(memory, "id", None),
                                )
                                if position != replacement:
                                    memory_context[position] = None
                                    del selected_vectors[position]
                            memory_context[replacement] = memory
                            selected_vectors[replacement] = unit
                            continue
                        if duplicates:
                            log.debug(
                                "diversity skip",
                                id=getattr(memory, "id", None),
                                reason="duplicate",
                            )
                            continue
                        selected_vectors[len(memory_context)] = unit

                memory_context.append(memory)

            if not progressed:
                # every list is exhausted at this depth
                break

            idx += 1

        return [memory for memory in memory_context if memory is not None]

    def _cut_to_budget(self, docs: list, max_tokens: int) -> list:
        kept: list = []
        for doc in docs:
            kept.append(doc)
            if util.count_tokens(kept) >= max_tokens:
                break
        return kept

    async def rerank(self, queries: list[str], docs: list) -> list:
        """Cross-encoder rerank of the merged candidates; unchanged on a load failure."""
        if not docs:
            return docs
        reranker = self.reranker
        result = await asyncio.to_thread(reranker.rerank, queries, docs, RERANK_KEEP)
        if reranker.error:
            return docs
        return result

    @property
    def embedding_function(self) -> Callable:
        raise NotImplementedError()

    async def embed_texts(self, texts: list[str]) -> np.ndarray:
        vectors = np.asarray(
            await asyncio.to_thread(self.embedding_function, texts), dtype=float
        )
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        return np.divide(vectors, norms, out=np.zeros_like(vectors), where=norms != 0)

    async def compare_strings(self, string1: str, string2: str) -> dict:
        vec1, vec2 = await self.embed_texts([string1, string2])
        return {
            "cosine_similarity": np.dot(vec1, vec2),
            "euclidean_distance": np.linalg.norm(vec1 - vec2),
        }

    async def compare_string_lists(
        self,
        list_a: list[str],
        list_b: list[str],
        similarity_threshold: float = None,
        distance_threshold: float = None,
    ) -> dict:
        """
        Compare two lists of strings using the current embedding function without touching the database.

        Returns a dictionary with:
            - 'cosine_similarity_matrix': np.ndarray of shape (len(list_a), len(list_b))
            - 'euclidean_distance_matrix': np.ndarray of shape (len(list_a), len(list_b))
            - 'similarity_matches': list of (i, j, score) (filtered if threshold set, otherwise all)
            - 'distance_matches': list of (i, j, distance) (filtered if threshold set, otherwise all)
        """
        if not list_a or not list_b:
            return {
                "cosine_similarity_matrix": np.array([]),
                "euclidean_distance_matrix": np.array([]),
                "similarity_matches": [],
                "distance_matches": [],
            }

        texts = list(dict.fromkeys((*list_a, *list_b)))
        vectors = dict(zip(texts, await self.embed_texts(texts)))
        vecs_a = np.array([vectors[text] for text in list_a])
        vecs_b = np.array([vectors[text] for text in list_b])
        cosine_similarity_matrix = np.dot(vecs_a, vecs_b.T)
        squared = (
            np.sum(vecs_a**2, axis=1)[:, None]
            + np.sum(vecs_b**2, axis=1)[None, :]
            - 2 * cosine_similarity_matrix
        )
        euclidean_distance_matrix = np.sqrt(np.maximum(squared, 0))

        # Prepare matches
        similarity_matches = []
        distance_matches = []

        # Populate similarity matches
        sim_indices = np.argwhere(
            cosine_similarity_matrix
            >= (similarity_threshold if similarity_threshold is not None else -np.inf)
        )
        for i, j in sim_indices:
            similarity_matches.append((i, j, cosine_similarity_matrix[i, j]))

        # Populate distance matches
        dist_indices = np.argwhere(
            euclidean_distance_matrix
            <= (distance_threshold if distance_threshold is not None else np.inf)
        )
        for i, j in dist_indices:
            distance_matches.append((i, j, euclidean_distance_matrix[i, j]))

        return {
            "cosine_similarity_matrix": cosine_similarity_matrix,
            "euclidean_distance_matrix": euclidean_distance_matrix,
            "similarity_matches": similarity_matches,
            "distance_matches": distance_matches,
        }


@register(condition=lambda: chromadb is not None)
class ChromaDBMemoryAgent(MemoryAgent):
    requires_llm_client = False

    @property
    def ready(self):
        if self.missing_hosted_embeddings_provider:
            return False

        if getattr(self, "db_client", None):
            return True
        return False

    @property
    def client_api_ready(self) -> bool:
        if self.using_client_api_embeddings:
            embeddings_client: ClientBase | None = instance.get_client(
                self.embeddings_client
            )
            if not embeddings_client:
                return False

            if not embeddings_client.supports_embeddings:
                return False

            if not embeddings_client.embeddings_status:
                return False

            if embeddings_client.current_status not in ["idle", "busy"]:
                return False

            return True

        return False

    @property
    def status(self):
        if self.using_client_api_embeddings and not self.client_api_ready:
            return "error"

        if self.ready:
            return "active" if not getattr(self, "processing", False) else "busy"

        if self.missing_hosted_embeddings_provider:
            return "error"

        return "waiting"

    @property
    def agent_details(self):
        details = {
            "backend": AgentDetail(
                icon="mdi-server-outline",
                value="ChromaDB",
                description="The backend to use for long-term memory",
            ).model_dump(),
            "embeddings": AgentDetail(
                icon="mdi-cube-unfolded",
                value=self.embeddings,
                description="The embeddings type.",
            ).model_dump(),
        }

        if self.model:
            details["model"] = AgentDetail(
                icon="mdi-brain",
                value=self.model,
                description="The embeddings model.",
            ).model_dump()

        if self.embeddings_client:
            details["client"] = AgentDetail(
                icon="mdi-network-outline",
                value=self.embeddings_client,
                description="The client to use for embeddings.",
            ).model_dump()

        if self.using_local_embeddings:
            details["device"] = AgentDetail(
                icon="mdi-memory",
                value=self.device,
                description="The device to use for embeddings.",
            ).model_dump()

        if self.retrieval_rerank:
            if self.rerank_error:
                details["rerank"] = AgentDetail(
                    icon="mdi-alert",
                    value="Rerank model failed to load",
                    description=f"{RERANK_MODEL}: {self.rerank_error}. Retrieval runs without the rerank.",
                    color="warning",
                ).model_dump()
            else:
                details["rerank"] = AgentDetail(
                    icon="mdi-sort-variant",
                    value=RERANK_MODEL,
                    description="The cross-encoder used to rerank retrieval results.",
                ).model_dump()

        missing_provider = self.missing_hosted_embeddings_provider
        if missing_provider:
            details["error"] = {
                "icon": "mdi-alert",
                "value": f"No {missing_provider} API key set",
                "description": f"You must provide an {missing_provider} API key to use {missing_provider} embeddings",
                "color": "error",
            }

        if self.using_client_api_embeddings:
            embeddings_client: ClientBase | None = instance.get_client(
                self.embeddings_client
            )

            if not embeddings_client:
                details["error"] = {
                    "icon": "mdi-alert",
                    "value": f"Client {self.embeddings_client} not found",
                    "description": f"Client {self.embeddings_client} not found",
                    "color": "error",
                }
                return details

            client_name = embeddings_client.name

            if not embeddings_client.supports_embeddings:
                error_message = f"{client_name} does not support embeddings"
            elif embeddings_client.current_status not in ["idle", "busy"]:
                error_message = f"{client_name} is not ready"
            elif not embeddings_client.embeddings_status:
                error_message = f"{client_name} has no embeddings model loaded"
            else:
                error_message = None

            if error_message:
                details["error"] = {
                    "icon": "mdi-alert",
                    "value": error_message,
                    "description": error_message,
                    "color": "error",
                }

        return details

    @property
    def db_name(self):
        return getattr(self, "collection_name", "<unnamed>")

    @property
    def openai_api_key(self):
        return self.config.openai.api_key

    @property
    def openrouter_api_key(self):
        return self.config.openrouter.api_key

    @property
    def missing_hosted_embeddings_provider(self) -> HostedEmbeddingsProvider | None:
        if self.using_openai_embeddings and not self.openai_api_key:
            return "OpenAI"

        if self.using_openrouter_embeddings and not self.openrouter_api_key:
            return "OpenRouter"

        return None

    @property
    def embedding_function(self) -> Callable:
        if (
            not self.db
            or not hasattr(self.db, "_embedding_function")
            or self.db._embedding_function is None
        ):
            raise RuntimeError(
                "Embedding function is not initialized. Make sure the database is set."
            )

        embed_fn = self.db._embedding_function
        return embed_fn

    def make_collection_name(self, scene) -> str:
        # generate plain text collection name
        collection_name = f"{self.fingerprint}"

        # chromadb collection names have the following rules:
        # Expected collection name that (1) contains 3-63 characters, (2) starts and ends with an alphanumeric character, (3) otherwise contains only alphanumeric characters, underscores or hyphens (-), (4) contains no two consecutive periods (..) and (5) is not a valid IPv4 address

        # Step 1: Hash the input string using MD5
        md5_hash = hashlib.md5(collection_name.encode()).hexdigest()

        # Step 2: Ensure the result is exactly 32 characters long
        hashed_collection_name = md5_hash[:32]

        return f"{scene.memory_id}-tm-{hashed_collection_name}"

    async def count(self):
        await asyncio.sleep(0)
        return self.db.count()

    def _set_db(self):
        self._ready_to_add = False

        # scene and generation have to be snapshotted together: a rebind between
        # the two reads would pair an old collection name with a post-bump
        # generation, and both install checks would pass
        with self._db_lock:
            generation = self._db_generation
            scene = self.scene

        collection_name = self.make_collection_name(scene)

        if not getattr(self, "db_client", None):
            log.info("chromadb agent", status="setting up db client to persistent db")
            self.db_client = chromadb.PersistentClient(
                settings=Settings(anonymized_telemetry=False)
            )

        log.info(
            "chromadb agent",
            status="setting up db",
            collection_name=collection_name,
            embeddings=self.embeddings,
        )

        db = self._build_collection(collection_name)
        count = db.count()

        with self._db_lock:
            if self._db_generation != generation or self.scene is not scene:
                # cleanup belongs to `close_db`, which works by name, so the stale
                # handle is simply dropped. accepted residual: this build may have
                # re-created the collection as an empty shell after `close_db`
                # deleted it - nothing was ever added to it and a later load of
                # the same scene reuses it
                log.warning(
                    "chromadb agent",
                    status="discarding stale db handle",
                    collection_name=collection_name,
                )
                return

            self.db = db
            self.collection_name = collection_name
            scene._memory_never_persisted = count == 0
            log.info("chromadb agent", status="db ready")
            self._ready_to_add = True

    def _openai_compatible_embedding_function(
        self,
        provider_label: HostedEmbeddingsProvider,
        api_key: str | None,
        model_name: str,
        api_base: str | None,
    ):
        if not api_key:
            raise ValueError(
                f"You must provide an {provider_label} API key in the config if you want to use it for chromadb embeddings"
            )

        log.info(
            "chromadb",
            embeddings=provider_label,
            api_key=api_key[:5] + "...",
            model=model_name,
            api_base=api_base,
        )

        return embedding_functions.OpenAIEmbeddingFunction(
            api_key=api_key,
            model_name=model_name,
            api_base=api_base,
        )

    def _build_collection(self, collection_name):
        distance_function = self.distance_function
        collection_metadata = {"hnsw:space": distance_function}
        device = self.actions["_config"].config["device"].value
        model_name = self.model

        if self.using_openai_embeddings or self.using_openrouter_embeddings:
            if self.using_openrouter_embeddings:
                provider_label, api_key, api_base = (
                    "OpenRouter",
                    self.openrouter_api_key,
                    OPENROUTER_EMBEDDINGS_BASE_URL,
                )
            else:
                provider_label, api_key, api_base = "OpenAI", self.openai_api_key, None

            ef = self._openai_compatible_embedding_function(
                provider_label, api_key, model_name, api_base
            )
            return self.db_client.get_or_create_collection(
                collection_name,
                embedding_function=ef,
                metadata=collection_metadata,
            )

        if self.using_client_api_embeddings:
            log.info(
                "chromadb",
                embeddings="Client API",
                client=self.embeddings_client,
            )

            embeddings_client: ClientBase | None = instance.get_client(
                self.embeddings_client
            )
            if not embeddings_client:
                raise ValueError(
                    f"Client API embeddings client {self.embeddings_client} not found"
                )

            if not embeddings_client.supports_embeddings:
                raise ValueError(
                    f"Client API embeddings client {self.embeddings_client} does not support embeddings"
                )

            ef = embeddings_client.embeddings_function

            return self.db_client.get_or_create_collection(
                collection_name, embedding_function=ef, metadata=collection_metadata
            )

        log.info(
            "chromadb",
            embeddings="SentenceTransformer",
            model=model_name,
            device=device,
            distance_function=distance_function,
        )

        try:
            # ChromaDB caches models in a class-level dict keyed only by model name,
            # ignoring device — so a device switch would silently reuse the old model.
            # Evict only when the cached model's device differs from the requested one,
            # otherwise reuse it (avoids an expensive reload on every set_db call).
            ST = embedding_functions.SentenceTransformerEmbeddingFunction
            cached = ST.models.get(model_name)
            if (
                cached is not None
                and getattr(cached, "device", None) is not None
                and cached.device.type != device
            ):
                self._release_embedding_model(ST.models.pop(model_name))

            ef = ST(
                model_name=model_name,
                trust_remote_code=self.trust_remote_code,
                device=device,
            )
        except ValueError as e:
            if "`trust_remote_code=True` to remove this error" in str(e):
                raise EmbeddingsModelLoadError(
                    model_name,
                    "Model requires `Trust remote code` to be enabled",
                )
            raise EmbeddingsModelLoadError(model_name, str(e))

        return self.db_client.get_or_create_collection(
            collection_name, embedding_function=ef, metadata=collection_metadata
        )

    def _cleanup_memory(
        self, scene, collection_name, db, remove_unsaved_memory: bool = True
    ):
        if not scene.saved and not scene.saved_memory_session_id:
            # scene was never saved so we can discard the memory
            log.info(
                "chromadb agent",
                status="discarding memory",
                collection_name=collection_name,
            )
            try:
                self.db_client.delete_collection(collection_name)
            except chromadb.errors.NotFoundError as exc:
                log.debug("chromadb agent", status="collection not found", details=exc)
            except ValueError as exc:
                log.error(
                    "chromadb agent", error="failed to delete collection", details=exc
                )
            return

        if not scene.saved and remove_unsaved_memory:
            # scene was saved but memory was never persisted
            # so we need to remove the memory from the db
            if not scene.memory_session_id:
                return

            if scene.saved_memory_session_id == scene.memory_session_id:
                return

            if db is None:
                try:
                    db = self.db_client.get_collection(collection_name)
                except chromadb.errors.NotFoundError:
                    return

            log.info(
                "chromadb agent",
                status="removing unsaved memory",
                session_id=scene.memory_session_id,
            )

            db.delete(
                where={
                    "$and": [
                        {"session": scene.memory_session_id},
                        {"source": "talemate"},
                    ]
                }
            )

    def clear_db(self):
        if not self.db:
            return

        log.info(
            "chromadb agent", status="clearing db", collection_name=self.collection_name
        )

        self.db.delete(where={"source": "talemate"})

    def drop_db(self):
        # the generation is bumped even without a handle, so an in-flight
        # `_set_db` cannot install a collection this call is about to delete
        with self._db_lock:
            self._db_generation += 1
            self._ready_to_add = False
            db = self.db
            collection_name = getattr(self, "collection_name", None)
            self.db = None

        if not db:
            return

        log.info(
            "chromadb agent", status="dropping db", collection_name=collection_name
        )

        try:
            self.db_client.delete_collection(collection_name)
        except chromadb.errors.NotFoundError as exc:
            log.debug("chromadb agent", status="collection not found", details=exc)
        except ValueError as exc:
            if "Collection not found" not in str(exc):
                raise

    def close_db(self, scene, remove_unsaved_memory: bool = True):
        # the handle is dropped and the generation bumped before the fallible
        # cleanup below: a raise must not leave the released scene's handle
        # installed past the agent's rebind, and an in-flight `_set_db` has to be
        # invalidated even when it has not installed its handle yet
        with self._db_lock:
            self._db_generation += 1
            self._ready_to_add = False
            db = self.db
            self.db = None

        if not getattr(self, "db_client", None):
            return

        collection_name = self.make_collection_name(scene)

        log.info("chromadb agent", status="closing db", collection_name=collection_name)

        self._cleanup_memory(scene, collection_name, db, remove_unsaved_memory)

    def _release_embedding_model(self, model):
        """Release an embedding model and free GPU memory if applicable."""
        try:
            import torch
        except ImportError:
            return

        if torch.cuda.is_available():
            model.to("cpu")
            del model

        release_cuda_cache()

    def _add(self, text, character=None, uid=None, ts: int = None, **kwargs):
        if character_knowledge_enabled(self.scene):
            kwargs["knowledge_index"] = False
        metadatas = []
        ids = []
        scene = self.scene

        if character:
            meta = {
                "character": character.name,
                "source": "talemate",
                "session": scene.memory_session_id,
            }
            if ts is not None:
                meta["ts"] = ts
            meta.update(kwargs)
            metadatas.append(meta)
            self.memory_tracker.setdefault(character.name, 0)
            self.memory_tracker[character.name] += 1
            id = uid or f"{character.name}-{self.memory_tracker[character.name]}"
            ids = [id]
        else:
            meta = {
                "character": "__narrator__",
                "source": "talemate",
                "session": scene.memory_session_id,
            }
            if ts is not None:
                meta["ts"] = ts
            meta.update(kwargs)
            metadatas.append(meta)
            self.memory_tracker.setdefault("__narrator__", 0)
            self.memory_tracker["__narrator__"] += 1
            id = uid or f"__narrator__-{self.memory_tracker['__narrator__']}"
            ids = [id]

        # log.debug("chromadb agent add", text=text, meta=meta, id=id)

        self.db.upsert(documents=[text], metadatas=metadatas, ids=ids)

    def _add_many(self, objects: list[dict]):
        documents = []
        metadatas = []
        ids = []
        scene = self.scene

        if not objects:
            return

        # track seen documents by id
        seen_ids = set()

        for obj in objects:
            if obj["id"] in seen_ids:
                log.warning(
                    "chromadb agent", status="duplicate id discarded", id=obj["id"]
                )
                continue
            seen_ids.add(obj["id"])

            documents.append(obj["text"])
            meta = dict(obj.get("meta", {}))
            if character_knowledge_enabled(scene):
                meta["knowledge_index"] = False
            source = meta.get("source", "talemate")
            character = meta.get("character", "__narrator__")
            self.memory_tracker.setdefault(character, 0)
            self.memory_tracker[character] += 1
            meta["source"] = source
            if not meta.get("session"):
                meta["session"] = scene.memory_session_id
            metadatas.append(meta)
            uid = obj.get("id", f"{character}-{self.memory_tracker[character]}")
            ids.append(uid)

        self.db.upsert(documents=documents, metadatas=metadatas, ids=ids)

    def _delete(self, meta: dict):
        if "ids" in meta:
            log.debug("chromadb agent delete", ids=meta["ids"])
            self.db.delete(ids=meta["ids"])
            return

        where = {"$and": [{k: v} for k, v in meta.items()]}

        # if there is only one item in $and reduce it to the key value pair
        if len(where["$and"]) == 1:
            where = where["$and"][0]

        self.db.delete(where=where)
        log.debug("chromadb agent delete", meta=meta, where=where)

    def _get(
        self,
        text,
        character=None,
        limit: int = 15,
        *,
        viewer=None,
        _collection=None,
        **kwargs,
    ):
        where = {}

        where.setdefault("$and", [])
        if character_knowledge_enabled(self.scene):
            where["$and"].extend(audience_where(viewer))
        elif viewer is not None:
            raise ValueError("A memory viewer requires perception mode")

        character_filtered = False

        for k, v in kwargs.items():
            if k == "character":
                character_filtered = True
            where["$and"].append({k: v})

        if character and not character_filtered:
            character_name = character if isinstance(character, str) else character.name
            where["$and"].append({"character": character_name})

        if len(where["$and"]) == 1:
            where = where["$and"][0]
        elif not where["$and"]:
            where = None

        log.debug("crhomadb agent get", text=text, where=where)

        try:
            _results = (_collection if _collection is not None else self.db).query(
                query_texts=[text],
                where=where,
                n_results=limit,
                include=["documents", "metadatas", "distances", "embeddings"],
            )
        except Exception as e:
            log.error("chromadb agent", error="failed to query", details=e)
            if viewer is not None:
                raise
            return []

        # import json
        # print(json.dumps(_results["ids"], indent=2))
        # print(json.dumps(_results["distances"], indent=2))

        results = []

        max_distance = self.max_distance

        closest = None

        active_memory_request = memory_request.get()

        embeddings = _results.get("embeddings")
        embeddings = embeddings[0] if embeddings is not None else None

        for i in range(len(_results["distances"][0])):
            distance = _results["distances"][0][i]

            doc = _results["documents"][0][i]
            meta = _results["metadatas"][0][i]
            embedding = None
            if embeddings is not None and i < len(embeddings):
                embedding = [float(x) for x in embeddings[i]]

            active_memory_request.add_result(doc, distance, meta)

            if not meta:
                continue

            ts = meta.get("ts")

            # skip pin_only entries
            if meta.get("pin_only", False):
                continue

            if closest is None:
                closest = {"distance": distance, "doc": doc}
            elif distance < closest["distance"]:
                closest = {"distance": distance, "doc": doc}

            if distance < max_distance:
                date_prefix = self.convert_ts_to_date_prefix(ts)
                raw = doc

                if date_prefix:
                    doc = f"{date_prefix}: {doc}"

                doc = MemoryDocument(
                    doc,
                    meta,
                    _results["ids"][0][i],
                    raw,
                    distance=distance,
                    embedding=embedding,
                )
                doc = render_fact_document(self.scene, doc)

                results.append(doc)
                active_memory_request.accept_result(str(doc), distance, meta)

            # log.debug("crhomadb agent get", result=results[-1], distance=distance)

            if len(results) > limit:
                break

        # log.debug("chromadb agent get", closest=closest, max_distance=max_distance)
        self.last_query = {
            "query": text,
            "closest": closest,
        }

        return results

    def convert_ts_to_date_prefix(self, ts):
        if ts is None:
            return None
        try:
            return util.diff_to_human(util.coerce_ts(ts), self.scene.ts)
        except Exception as e:
            log.error(
                "chromadb agent",
                error="failed to get date prefix",
                details=e,
                ts=ts,
                scene_ts=self.scene.ts,
            )
            return None

    def _get_embeddings(self, ids: list[str]) -> dict[str, list[float]]:
        result = self.db.get(ids=list(ids), include=["embeddings"])
        embeddings = result.get("embeddings")
        if embeddings is None:
            return {}
        return {
            doc_id: np.asarray(vector, dtype=float).tolist()
            for doc_id, vector in zip(result.get("ids", []), embeddings)
        }

    def _get_document(self, id) -> dict:
        if not id:
            return {}

        result = self.db.get(ids=[id] if isinstance(id, str) else id)
        return self._documents_from(result)

    def _get_documents_by_meta(
        self, meta: dict, *, viewer=None, _collection=None
    ) -> dict:
        clauses = [{key: value} for key, value in meta.items()]
        if character_knowledge_enabled(self.scene):
            clauses.extend(audience_where(viewer))
        elif viewer is not None:
            raise ValueError("A memory viewer requires perception mode")
        where = clauses[0] if len(clauses) == 1 else {"$and": clauses}
        db = self.db if _collection is None else _collection
        return self._documents_from(db.get(where=where))

    def _documents_from(self, result) -> dict:
        documents = {}
        for idx, doc in enumerate(result["documents"]):
            documents[result["ids"][idx]] = self._dated_document(
                doc, result["metadatas"][idx], result["ids"][idx]
            )
        return documents

    def _dated_document(self, raw, meta, identity):
        date_prefix = self.convert_ts_to_date_prefix(meta.get("ts"))
        text = f"{date_prefix}: {raw}" if date_prefix else raw
        return render_fact_document(
            self.scene, MemoryDocument(text, meta, identity, raw)
        )

    @set_processing
    async def remove_unsaved_memory(self):
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._remove_unsaved_memory)

    def _remove_unsaved_memory(self):
        scene = self.scene
        self._cleanup_memory(scene, self.make_collection_name(scene), self.db)
