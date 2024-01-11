from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING, Callable, List, Optional, Union
from chromadb.config import Settings
import talemate.events as events
import talemate.util as util
from talemate.emit import emit
from talemate.emit.signals import handlers
from talemate.context import scene_is_loading
from talemate.config import load_config
from talemate.agents.base import set_processing
import structlog
import shutil
import functools

try:
    import chromadb
    from chromadb.utils import embedding_functions
except ImportError:
    chromadb = None
    pass

log = structlog.get_logger("talemate.agents.memory")

if not chromadb:
    log.info("ChromaDB not found, disabling Chroma agent")


from .base import Agent

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
    verbose_name = "Long-term memory"

    @property
    def readonly(self):
        
        if scene_is_loading.get() and not getattr(self.scene, "_memory_never_persisted", False):
            return True
        
        return False

    @property
    def db_name(self):
        raise NotImplementedError()

    @classmethod
    def config_options(cls, agent=None):
        return {}

    def __init__(self, scene, **kwargs):
        self.db = None
        self.scene = scene
        self.memory_tracker = {}
        self.config = load_config()
        self._ready_to_add = False
        
        handlers["config_saved"].connect(self.on_config_saved)
        
    def on_config_saved(self, event):
        openai_key = self.openai_api_key
        self.config = load_config()
        if openai_key != self.openai_api_key:
            loop = asyncio.get_running_loop()
            loop.run_until_complete(self.emit_status())

    async def set_db(self):
        raise NotImplementedError()

    def close_db(self):
        raise NotImplementedError()

    async def count(self):
        raise NotImplementedError()

    @set_processing
    async def add(self, text, character=None, uid=None, ts:str=None, **kwargs):
        if not text:
            return
        if self.readonly:
            log.debug("memory agent", status="readonly")
            return
        
        while not self._ready_to_add:
            await asyncio.sleep(0.1)
            
        log.debug("memory agent add", text=text[:50], character=character, uid=uid, ts=ts, **kwargs)
         
        loop = asyncio.get_running_loop()
        
        await loop.run_in_executor(None, functools.partial(self._add, text, character, uid=uid, ts=ts, **kwargs))

    def _add(self, text, character=None, ts:str=None, **kwargs):
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

    def _delete(self, meta:dict):
        """
        Delete an object from the memory
        """
        raise NotImplementedError()
    
    @set_processing
    async def delete(self, meta:dict):
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

    @set_processing
    async def get(self, text, character=None, **query):
        loop = asyncio.get_running_loop()
        
        return await loop.run_in_executor(None, functools.partial(self._get, text, character, **query))

    def _get(self, text, character=None, **query):
        raise NotImplementedError()

    @set_processing
    async def get_document(self, id):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._get_document, id)
    
    def _get_document(self, id):
        raise NotImplementedError()

    def on_archive_add(self, event: events.ArchiveEvent):
        asyncio.ensure_future(self.add(event.text, uid=event.memory_id, ts=event.ts, typ="history"))

    def on_character_state(self, event: events.CharacterStateEvent):
        asyncio.ensure_future(
            self.add(event.state, uid=f"description-{event.character_name}")
        )

    def connect(self, scene):
        super().connect(scene)
        scene.signals["archive_add"].connect(self.on_archive_add)
        scene.signals["character_state"].connect(self.on_character_state)

    def add_chunks(self, lines: list[str], chunk_size=200):
        current_chunk = []
        current_size = 0
        for line in lines:
            current_size += util.count_tokens(line)

            if current_size > chunk_size:
                self.add("\n".join(current_chunk))
                current_chunk = [line]
                current_size = util.count_tokens(line)
            else:
                current_chunk.append(line)

        if current_chunk:
            self.add("\n".join(current_chunk))

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

    async def query(self, query:str, max_tokens:int=1000, filter:Callable=lambda x:True, **where):
        """
        Get the character memory context for a given character
        """

        try:
            return (await self.multi_query([query], max_tokens=max_tokens, filter=filter, **where))[0]
        except IndexError:
            return None


    async def multi_query(
        self,
        queries: list[str],
        iterate: int = 1,
        max_tokens: int = 1000,
        filter: Callable = lambda x: True,
        formatter: Callable = lambda x: x,
        limit: int = 10,
        **where
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


from .registry import register


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
        
        if self.embeddings == "openai" and not self.openai_api_key:
            return "No OpenAI API key set"
        
        return f"ChromaDB: {self.embeddings}"
    
    @property
    def embeddings(self):
        """
        Returns which embeddings to use
        
        will read from TM_CHROMADB_EMBEDDINGS env variable and default to 'default' using
        the default embeddings specified by chromadb.
        
        other values are
        
        - openai: use openai embeddings
        - instructor: use instructor embeddings
        
        for `openai`:
        
        you will also need to provide an `OPENAI_API_KEY` env variable
        
        for `instructor`:
        
        you will also need to provide which instructor model to use with the `TM_INSTRUCTOR_MODEL` env variable, which defaults to hkunlp/instructor-xl
        
        additionally you can provide the `TM_INSTRUCTOR_DEVICE` env variable to specify which device to use, which defaults to cpu
        """
        
        embeddings = self.config.get("chromadb").get("embeddings")
        
        assert embeddings in ["default", "openai", "instructor"], f"Unknown embeddings {embeddings}"
        
        return embeddings
    
    @property
    def USE_OPENAI(self):
        return self.embeddings == "openai"
    
    @property
    def USE_INSTRUCTOR(self):
        return self.embeddings == "instructor"
    
    @property
    def db_name(self):
        return getattr(self, "collection_name", "<unnamed>")

    @property
    def openai_api_key(self):
        return self.config.get("openai",{}).get("api_key")

    def make_collection_name(self, scene):
        
        if self.USE_OPENAI:
            suffix = "-openai"
        elif self.USE_INSTRUCTOR:
            suffix = "-instructor"
            model = self.config.get("chromadb").get("instructor_model", "hkunlp/instructor-xl")
            if "xl" in model:
                suffix += "-xl"
            elif "large" in model:
                suffix += "-large"
        else:
            suffix = ""
        
        return f"{scene.memory_id}-tm{suffix}"

    async def count(self):
        await asyncio.sleep(0)
        return self.db.count()

    @set_processing
    async def set_db(self):
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._set_db)

    def _set_db(self):
        
        self._ready_to_add = False
        
        if not getattr(self, "db_client", None):
            log.info("chromadb agent", status="setting up db client to persistent db")
            self.db_client = chromadb.PersistentClient(
                settings=Settings(anonymized_telemetry=False)
            )

        openai_key = self.openai_api_key
        
        self.collection_name = collection_name = self.make_collection_name(self.scene)
        
        log.info("chromadb agent", status="setting up db", collection_name=collection_name)
        
        if self.USE_OPENAI:
            
            if not openai_key:
                raise ValueError("You must provide an the openai ai key in the config if you want to use it for chromadb embeddings")
            
            log.info(
                "crhomadb", status="using openai", openai_key=openai_key[:5] + "..."
            )
            openai_ef = embedding_functions.OpenAIEmbeddingFunction(
                api_key = openai_key,
                model_name="text-embedding-ada-002",
            )
            self.db = self.db_client.get_or_create_collection(
                collection_name, embedding_function=openai_ef
            )
        elif self.USE_INSTRUCTOR:
            
            instructor_device = self.config.get("chromadb").get("instructor_device", "cpu")
            instructor_model = self.config.get("chromadb").get("instructor_model", "hkunlp/instructor-xl")
            
            log.info("chromadb", status="using instructor", model=instructor_model, device=instructor_device)
            
            # ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-mpnet-base-v2")
            ef = embedding_functions.InstructorEmbeddingFunction(
                model_name=instructor_model, device=instructor_device
            )
            
            log.info("chromadb", status="embedding function ready")
            
            self.db = self.db_client.get_or_create_collection(
                collection_name, embedding_function=ef
            )
            
            log.info("chromadb", status="instructor db ready")
        else:
            log.info("chromadb", status="using default embeddings")
            self.db = self.db_client.get_or_create_collection(collection_name)
        
        self.scene._memory_never_persisted = self.db.count() == 0
        log.info("chromadb agent", status="db ready")
        self._ready_to_add = True

    def clear_db(self):
        if not self.db:
            return
        
        log.info("chromadb agent", status="clearing db", collection_name=self.collection_name)
        
        self.db.delete(where={"source": "talemate"})
        
    def drop_db(self):
        if not self.db:
            return
        
        log.info("chromadb agent", status="dropping db", collection_name=self.collection_name)
        
        try:
            self.db_client.delete_collection(self.collection_name)
        except ValueError as exc:
            if "Collection not found" not in str(exc):
                raise

    def close_db(self, scene):
        if not self.db:
            return
        
        log.info("chromadb agent", status="closing db", collection_name=self.collection_name)
        
        if not scene.saved and not scene.saved_memory_session_id:
            # scene was never saved so we can discard the memory
            collection_name = self.make_collection_name(scene)
            log.info("chromadb agent", status="discarding memory", collection_name=collection_name)
            try:
                self.db_client.delete_collection(collection_name)
            except ValueError as exc:
                if "Collection not found" not in str(exc):
                    raise
        elif not scene.saved:
            # scene was saved but memory was never persisted
            # so we need to remove the memory from the db
            self._remove_unsaved_memory()
        
        self.db = None
        
    def _add(self, text, character=None, uid=None, ts:str=None, **kwargs):
        metadatas = []
        ids = []
        scene = self.scene
        
        if character:
            meta = {"character": character.name, "source": "talemate", "session": scene.memory_session_id}
            if ts:
                meta["ts"] = ts
            meta.update(kwargs)
            metadatas.append(meta)
            self.memory_tracker.setdefault(character.name, 0)
            self.memory_tracker[character.name] += 1
            id = uid or f"{character.name}-{self.memory_tracker[character.name]}"
            ids = [id]
        else:
            meta = {"character": "__narrator__", "source": "talemate", "session": scene.memory_session_id}
            if ts:
                meta["ts"] = ts
            meta.update(kwargs)
            metadatas.append(meta)
            self.memory_tracker.setdefault("__narrator__", 0)
            self.memory_tracker["__narrator__"] += 1
            id = uid or f"__narrator__-{self.memory_tracker['__narrator__']}"
            ids = [id]

        #log.debug("chromadb agent add", text=text, meta=meta, id=id)

        self.db.upsert(documents=[text], metadatas=metadatas, ids=ids)

    def _add_many(self, objects: list[dict]):
        
        documents = []
        metadatas = []
        ids = []
        scene = self.scene

        for obj in objects:
            documents.append(obj["text"])
            meta = obj.get("meta", {})
            source = meta.get("source", "talemate")
            character = meta.get("character", "__narrator__")
            self.memory_tracker.setdefault(character, 0)
            self.memory_tracker[character] += 1
            meta["source"] = source
            meta["session"] = scene.memory_session_id
            metadatas.append(meta)
            uid = obj.get("id", f"{character}-{self.memory_tracker[character]}")
            ids.append(uid)
        self.db.upsert(documents=documents, metadatas=metadatas, ids=ids)

    def _delete(self, meta:dict):
        
        if "ids" in meta:
            log.debug("chromadb agent delete", ids=meta["ids"])
            self.db.delete(ids=meta["ids"])
            return
        
        where = {"$and": [{k:v} for k,v in meta.items()]}
        self.db.delete(where=where)
        log.debug("chromadb agent delete", meta=meta, where=where)

    def _get(self, text, character=None, limit:int=15, **kwargs):
        where = {}
        where.setdefault("$and", [])
        
        character_filtered = False
        
        for k,v in kwargs.items():
            if k == "character":
                character_filtered = True
            where["$and"].append({k: v})


        if character and not character_filtered:
            where["$and"].append({"character": character.name})
            
        if len(where["$and"]) == 1:
            where = where["$and"][0]
        elif not where["$and"]:
            where = None

        #log.debug("crhomadb agent get", text=text, where=where)

        _results = self.db.query(query_texts=[text], where=where, n_results=limit)
        
        #import json
        #print(json.dumps(_results["ids"], indent=2))
        #print(json.dumps(_results["distances"], indent=2))
        
        results = []
        
        max_distance = 1.5
        if self.USE_INSTRUCTOR:
            max_distance = 1
        elif self.USE_OPENAI:
            max_distance = 1

        for i in range(len(_results["distances"][0])):
            distance = _results["distances"][0][i]
            
            doc = _results["documents"][0][i]
            meta = _results["metadatas"][0][i]
            ts = meta.get("ts")
            
            if distance < max_distance:
                
                try:
                    #log.debug("chromadb agent get", ts=ts, scene_ts=self.scene.ts)
                    date_prefix = util.iso8601_diff_to_human(ts, self.scene.ts)
                except Exception as e:
                    log.error("chromadb agent", error="failed to get date prefix", details=e, ts=ts, scene_ts=self.scene.ts)
                    date_prefix = None
                
                raw = doc
                
                if date_prefix:
                    doc = f"{date_prefix}: {doc}"
                    
                doc = MemoryDocument(doc, meta, _results["ids"][0][i], raw)
                    
                results.append(doc)
            else:
                break

            # log.debug("crhomadb agent get", result=results[-1], distance=distance)

            if len(results) > limit:
                break

        return results

    def _get_document(self, id) -> dict:
        result = self.db.get(ids=[id] if isinstance(id, str) else id)
        documents = {}
        
        for idx, doc in enumerate(result["documents"]):
            documents[result["ids"][idx]] = MemoryDocument(doc, result["metadatas"][idx], result["ids"][idx], doc)
            
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
        
        log.info("chromadb agent", status="removing unsaved memory", session_id=scene.memory_session_id)
        
        self._delete({"session": scene.memory_session_id, "source": "talemate"})
        
    
