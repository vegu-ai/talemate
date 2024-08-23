from __future__ import annotations

import asyncio
import functools
import hashlib
import uuid
from typing import Callable

import structlog
from chromadb.config import Settings

import talemate.events as events
import talemate.util as util
from talemate.agents.base import (
    Agent,
    AgentAction,
    AgentActionConfig,
    AgentDetail,
    set_processing,
)
from talemate.config import load_config
from talemate.context import scene_is_loading, active_scene
from talemate.emit import emit
from talemate.emit.signals import handlers
from talemate.agents.memory.context import memory_request, MemoryRequest
from talemate.agents.memory.exceptions import (
    EmbeddingsModelLoadError,
    SetDBError,
)

try:
    import chromadb
    from chromadb.utils import embedding_functions
except ImportError:
    chromadb = None
    pass

log = structlog.get_logger("talemate.agents.memory")

if not chromadb:
    log.info("ChromaDB not found, disabling Chroma agent")


from talemate.agents.registry import register

class MemoryDocument(str):
    def __new__(cls, text, meta, id, raw):
        inst = super().__new__(cls, text)

        inst.meta = meta
        inst.id = id
        inst.raw = raw

        return inst


class MemoryAgent(Agent):
    """
    An agent that can be used to maintain and access a memory of the world
    using vector databases
    """

    agent_type = "memory"
    verbose_name = "Memory"

    def __init__(self, scene, **kwargs):
        self.db = None
        self.scene = scene
        self.memory_tracker = {}
        self.config = load_config()
        self._ready_to_add = False

        handlers["config_saved"].connect(self.on_config_saved)
        
        self.actions = {
            "_config": AgentAction(
                enabled=True,
                label="Configure",
                description="Memory agent configuration",
                config={
                    "embeddings": AgentActionConfig(
                        type="text",
                        value="default",
                        label="Embeddings",
                        choices=self.get_presets,
                        description="Which embeddings to use",
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
                        ]
                    ),
                },
            ),
        }

    @property
    def readonly(self):
        if scene_is_loading.get() and not getattr(
            self.scene, "_memory_never_persisted", False
        ):
            return True

        return False

    @property
    def db_name(self):
        raise NotImplementedError()
    
    @property
    def get_presets(self):
        return [
            {"value": k, "label": f"{v['embeddings']}: {v['model']}"} for k,v in self.config.get("presets", {}).get("embeddings", {}).items()
        ]
        
    @property
    def embeddings_config(self):
        _embeddings = self.actions["_config"].config["embeddings"].value
        return self.config.get("presets", {}).get("embeddings", {}).get(_embeddings, {})
    
    @property
    def embeddings(self):
        return self.embeddings_config.get("embeddings", "sentence-transformer")
        
    @property
    def using_openai_embeddings(self):
        return self.embeddings == "openai"

    @property
    def using_instructor_embeddings(self):
        return self.embeddings == "instructor"
    
    @property
    def using_sentence_transformer_embeddings(self):
        return self.embeddings == "default" or self.embeddings == "sentence-transformer"
    
    @property
    def using_local_embeddings(self):
        return self.embeddings in [
            "instructor",
            "sentence-transformer",
            "default"
        ]
    
    @property
    def max_distance(self) -> float:
        distance = float(self.embeddings_config.get("distance", 1.0))
        distance_mod = float(self.embeddings_config.get("distance_mod", 1.0))
        
        return distance * distance_mod
    
    @property
    def model(self):
        return self.embeddings_config.get("model")
    
    @property
    def distance_function(self):
        return self.embeddings_config.get("distance_function", "l2")

    @property
    def device(self) -> str:
        return self.actions["_config"].config["device"].value

    @property
    def trust_remote_code(self) -> bool:
        return self.embeddings_config.get("trust_remote_code", False)

    @property
    def fingerprint(self) -> str:
        """
        Returns a unique fingerprint for the current configuration
        """
        return f"{self.embeddings}-{self.model.replace('/','-')}-{self.distance_function}-{self.device}-{self.trust_remote_code}".lower()   

    async def apply_config(self, *args, **kwargs):
        
        _fingerprint = self.fingerprint
        
        await super().apply_config(*args, **kwargs)
        
        fingerprint_changed = _fingerprint != self.fingerprint
        
        # have embeddings or device changed?
        if fingerprint_changed:
            log.warning("memory agent", status="embedding function changed", old=_fingerprint, new=self.fingerprint)
            await self.handle_embeddings_change()
            
    
    @set_processing
    async def handle_embeddings_change(self):
        scene = active_scene.get()
        
        if not scene or not scene.get_helper("memory"):
            return
        
        self.close_db(scene)
        emit("status", "Re-importing context database", status="busy")
        await scene.commit_to_memory()
        await scene.save()

    def on_config_saved(self, event):
        loop = asyncio.get_running_loop()
        openai_key = self.openai_api_key
        
        fingerprint = self.fingerprint
        
        self.config = load_config()
            
        if fingerprint != self.fingerprint:
            log.warning("memory agent", status="embedding function changed", old=fingerprint, new=self.fingerprint)
            loop.run_until_complete(self.handle_embeddings_change())
            
        if openai_key != self.openai_api_key:
            loop.run_until_complete(self.emit_status())

    @set_processing
    async def set_db(self):
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._set_db)
        except EmbeddingsModelLoadError:
            raise
        except Exception as e:
            log.error("memory agent", error="failed to set db", details=e)
            
            if "torchvision::nms does not exist" in str(e):
                raise SetDBError("The embeddings you are trying to use require the `torchvision` package to be installed")
            
            raise SetDBError(str(e))


    def close_db(self):
        raise NotImplementedError()

    async def count(self):
        raise NotImplementedError()

    @set_processing
    async def add(self, text, character=None, uid=None, ts: str = None, **kwargs):
        if not text:
            return
        if self.readonly:
            log.debug("memory agent", status="readonly")
            return

        while not self._ready_to_add:
            await asyncio.sleep(0.1)

        log.debug(
            "memory agent add",
            text=text[:50],
            character=character,
            uid=uid,
            ts=ts,
            **kwargs,
        )

        loop = asyncio.get_running_loop()

        try:
            await loop.run_in_executor(
                None,
                functools.partial(self._add, text, character, uid=uid, ts=ts, **kwargs),
            )
        except AttributeError as e:
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
                await loop.run_in_executor(
                    None,
                    functools.partial(
                        self._add, text, character, uid=uid, ts=ts, **kwargs
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

    def _add(self, text, character=None, ts: str = None, **kwargs):
        raise NotImplementedError()

    @set_processing
    async def add_many(self, objects: list[dict]):
        if self.readonly:
            log.debug("memory agent", status="readonly")
            return

        while not self._ready_to_add:
            await asyncio.sleep(0.1)

        log.debug("memory agent add many", len=len(objects))

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._add_many, objects)

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
        if self.readonly:
            log.debug("memory agent", status="readonly")
            return

        while not self._ready_to_add:
            await asyncio.sleep(0.1)

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._delete, meta)

    def _delete(self, meta: dict):
        """
        Delete an object from the memory
        """
        raise NotImplementedError()

    @set_processing
    async def get(self, text, character=None, **query):
        with MemoryRequest(query=text, query_params=query) as active_memory_request:
            active_memory_request.max_distance = self.max_distance
            return await asyncio.to_thread(self._get, text, character, **query)
            #return await loop.run_in_executor(
            #    None, functools.partial(self._get, text, character, **query)
            #)

    def _get(self, text, character=None, **query):
        raise NotImplementedError()

    @set_processing
    async def get_document(self, id):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._get_document, id)

    def _get_document(self, id):
        raise NotImplementedError()

    def on_archive_add(self, event: events.ArchiveEvent):
        asyncio.ensure_future(
            self.add(event.text, uid=event.memory_id, ts=event.ts, typ="history")
        )

    def connect(self, scene):
        super().connect(scene)
        scene.signals["archive_add"].connect(self.on_archive_add)

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

        for memory in await self.get(query):
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
        filter: Callable = lambda x: True,
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
        filter: Callable = lambda x: True,
        formatter: Callable = lambda x: x,
        limit: int = 10,
        **where,
    ):
        """
        Get the character memory context for a given character
        """

        memory_context = []
        for query in queries:
            if not query:
                continue

            i = 0
            for memory in await self.get(formatter(query), limit=limit, **where):
                if memory in memory_context:
                    continue

                if filter and not filter(memory):
                    continue

                memory_context.append(memory)

                i += 1
                if i >= iterate:
                    break

                if util.count_tokens(memory_context) >= max_tokens:
                    break
            if util.count_tokens(memory_context) >= max_tokens:
                break
        return memory_context


@register(condition=lambda: chromadb is not None)
class ChromaDBMemoryAgent(MemoryAgent):
    requires_llm_client = False

    @property
    def ready(self):
        if self.embeddings == "openai" and not self.openai_api_key:
            return False

        if getattr(self, "db_client", None):
            return True
        return False

    @property
    def status(self):
        if self.ready:
            return "active" if not getattr(self, "processing", False) else "busy"

        if self.embeddings == "openai" and not self.openai_api_key:
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
            "model": AgentDetail(
                icon="mdi-brain",
                value=self.model,
                description="The embeddings model.",
            ).model_dump(),
        }
        
        if self.using_local_embeddings:
            details["device"] = AgentDetail(
                icon="mdi-memory",
                value=self.device,
                description="The device to use for embeddings.",
            ).model_dump()

        if self.embeddings == "openai" and not self.openai_api_key:
            # return "No OpenAI API key set"
            details["error"] = {
                "icon": "mdi-alert",
                "value": "No OpenAI API key set",
                "description": "You must provide an OpenAI API key to use OpenAI embeddings",
                "color": "error",
            }

        return details

    @property
    def db_name(self):
        return getattr(self, "collection_name", "<unnamed>")

    @property
    def openai_api_key(self):
        return self.config.get("openai", {}).get("api_key")

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

        if not getattr(self, "db_client", None):
            log.info("chromadb agent", status="setting up db client to persistent db")
            self.db_client = chromadb.PersistentClient(
                settings=Settings(anonymized_telemetry=False)
            )

        openai_key = self.openai_api_key

        self.collection_name = collection_name = self.make_collection_name(self.scene)

        log.info(
            "chromadb agent", status="setting up db", collection_name=collection_name
        )
        
        distance_function = self.distance_function
        collection_metadata = {"hnsw:space": distance_function}
        device =  self.actions["_config"].config["device"].value
        model_name = self.model
        
        if self.using_openai_embeddings:
            if not openai_key:
                raise ValueError(
                    "You must provide an the openai ai key in the config if you want to use it for chromadb embeddings"
                )

            log.info(
                "chromadb",
                embeddings="OpenAI",
                openai_key=openai_key[:5] + "...",
                model=model_name,
            )
            openai_ef = embedding_functions.OpenAIEmbeddingFunction(
                api_key=openai_key,
                model_name=model_name,
            )
            self.db = self.db_client.get_or_create_collection(
                collection_name, embedding_function=openai_ef, metadata=collection_metadata
            )
        elif self.using_instructor_embeddings:
            log.info(
                "chromadb",
                embeddings="Instructor-XL",
                model=model_name,
                device=device,
            )

            ef = embedding_functions.InstructorEmbeddingFunction(
                model_name=model_name, device=device
            )

            log.info("chromadb", status="embedding function ready")
            self.db = self.db_client.get_or_create_collection(
                collection_name, embedding_function=ef, metadata=collection_metadata
            )
            log.info("chromadb", status="instructor db ready")
        else:
            log.info(
                "chromadb", 
                embeddins="SentenceTransformer", 
                model=model_name,
                device=device,
                distance_function=distance_function
            )
            
            try:
                ef = embedding_functions.SentenceTransformerEmbeddingFunction(
                    model_name=model_name,
                    trust_remote_code=self.trust_remote_code,
                    device=device
                )
            except ValueError as e:
                if "`trust_remote_code=True` to remove this error" in str(e):
                    raise EmbeddingsModelLoadError(model_name, "Model requires `Trust remote code` to be enabled")
                raise EmbeddingsModelLoadError(model_name, str(e))
                
            
            self.db = self.db_client.get_or_create_collection(
                collection_name, embedding_function=ef, metadata=collection_metadata
            )

        self.scene._memory_never_persisted = self.db.count() == 0
        log.info("chromadb agent", status="db ready")
        self._ready_to_add = True

    def clear_db(self):
        if not self.db:
            return

        log.info(
            "chromadb agent", status="clearing db", collection_name=self.collection_name
        )

        self.db.delete(where={"source": "talemate"})

    def drop_db(self):
        if not self.db:
            return

        log.info(
            "chromadb agent", status="dropping db", collection_name=self.collection_name
        )

        try:
            self.db_client.delete_collection(self.collection_name)
        except ValueError as exc:
            if "Collection not found" not in str(exc):
                raise

    def close_db(self, scene, remove_unsaved_memory: bool = True):
        if not self.db:
            return

        log.info(
            "chromadb agent", status="closing db", collection_name=self.collection_name
        )

        if not scene.saved and not scene.saved_memory_session_id:
            # scene was never saved so we can discard the memory
            collection_name = self.make_collection_name(scene)
            log.info(
                "chromadb agent",
                status="discarding memory",
                collection_name=collection_name,
            )
            try:
                self.db_client.delete_collection(collection_name)
            except ValueError as exc:
                log.error(
                    "chromadb agent", error="failed to delete collection", details=exc
                )
        elif not scene.saved and remove_unsaved_memory:
            # scene was saved but memory was never persisted
            # so we need to remove the memory from the db
            self._remove_unsaved_memory()

        self.db = None

    def _add(self, text, character=None, uid=None, ts: str = None, **kwargs):
        metadatas = []
        ids = []
        scene = self.scene

        if character:
            meta = {
                "character": character.name,
                "source": "talemate",
                "session": scene.memory_session_id,
            }
            if ts:
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
            if ts:
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

        for obj in objects:
            documents.append(obj["text"])
            meta = obj.get("meta", {})
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
        self.db.delete(where=where)
        log.debug("chromadb agent delete", meta=meta, where=where)

    def _get(self, text, character=None, limit: int = 15, **kwargs):
        where = {}

        # this doesn't work because chromadb currently doesn't match
        # non existing fields with $ne (or so it seems)
        # where.setdefault("$and", [{"pin_only": {"$ne": True}}])

        where.setdefault("$and", [])

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

        # log.debug("crhomadb agent get", text=text, where=where)

        _results = self.db.query(query_texts=[text], where=where, n_results=limit)

        #import json
        #print(json.dumps(_results["ids"], indent=2))
        #print(json.dumps(_results["distances"], indent=2))

        results = []

        max_distance = self.max_distance
        
        closest = None
        
        active_memory_request = memory_request.get()

        for i in range(len(_results["distances"][0])):
            distance = _results["distances"][0][i]

            doc = _results["documents"][0][i]
            meta = _results["metadatas"][0][i]
            
            active_memory_request.add_result(doc, distance, meta)

            if not meta:
                log.warning("chromadb agent get", error="no meta", doc=doc)
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

                doc = MemoryDocument(doc, meta, _results["ids"][0][i], raw)

                results.append(doc)
                active_memory_request.accept_result(str(doc), distance, meta)

            # log.debug("crhomadb agent get", result=results[-1], distance=distance)

            if len(results) > limit:
                break
            
        log.debug("chromadb agent get", closest=closest, max_distance=max_distance)
        self.last_query = {
            "query": text,
            "closest": closest,
        }
        
        return results

    def convert_ts_to_date_prefix(self, ts):
        if not ts:
            return None
        try:
            return util.iso8601_diff_to_human(ts, self.scene.ts)
        except Exception as e:
            log.error(
                "chromadb agent",
                error="failed to get date prefix",
                details=e,
                ts=ts,
                scene_ts=self.scene.ts,
            )
            return None

    def _get_document(self, id) -> dict:
        result = self.db.get(ids=[id] if isinstance(id, str) else id)
        documents = {}

        for idx, doc in enumerate(result["documents"]):
            date_prefix = self.convert_ts_to_date_prefix(
                result["metadatas"][idx].get("ts")
            )
            if date_prefix:
                doc = f"{date_prefix}: {doc}"
            documents[result["ids"][idx]] = MemoryDocument(
                doc, result["metadatas"][idx], result["ids"][idx], doc
            )

        return documents

    @set_processing
    async def remove_unsaved_memory(self):
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._remove_unsaved_memory)

    def _remove_unsaved_memory(self):
        scene = self.scene

        if not scene.memory_session_id:
            return

        if scene.saved_memory_session_id == self.scene.memory_session_id:
            return

        log.info(
            "chromadb agent",
            status="removing unsaved memory",
            session_id=scene.memory_session_id,
        )

        self._delete({"session": scene.memory_session_id, "source": "talemate"})
