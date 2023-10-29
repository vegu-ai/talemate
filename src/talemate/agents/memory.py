from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING, Callable, List, Optional, Union
from chromadb.config import Settings
import talemate.events as events
import talemate.util as util
from talemate.context import scene_is_loading
from talemate.config import load_config
import structlog
import shutil

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

    async def set_db(self):
        raise NotImplementedError()

    def close_db(self):
        raise NotImplementedError()

    async def count(self):
        raise NotImplementedError()

    async def add(self, text, character=None, uid=None, ts:str=None, **kwargs):
        if not text:
            return
        if self.readonly:
            log.debug("memory agent", status="readonly")
            return
        await self._add(text, character=character, uid=uid, ts=ts, **kwargs)

    async def _add(self, text, character=None, ts:str=None, **kwargs):
        raise NotImplementedError()

    async def add_many(self, objects: list[dict]):
        if self.readonly:
            log.debug("memory agent", status="readonly")
            return
        await self._add_many(objects)
    
    async def _add_many(self, objects: list[dict]):
        """
        Add multiple objects to the memory
        """
        raise NotImplementedError()

    async def get(self, text, character=None, **query):
        return await self._get(str(text), character, **query)

    async def _get(self, text, character=None, **query):
        raise NotImplementedError()

    def get_document(self, id):
        return self.db.get(id)

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
        for memory in await self.get(query):
            if memory in memory_context:
                continue

            if filter and not filter(memory):
                continue

            memory_context.append(memory)

            if util.count_tokens(memory_context) >= max_tokens:
                break
        return memory_context

    async def query(self, query:str, max_tokens:int=1000, filter:Callable=lambda x:True):
        """
        Get the character memory context for a given character
        """

        try:
            return (await self.multi_query([query], max_tokens=max_tokens, filter=filter))[0]
        except IndexError:
            return None


    async def multi_query(
        self,
        queries: list[str],
        iterate: int = 1,
        max_tokens: int = 1000,
        filter: Callable = lambda x: True,
        formatter: Callable = lambda x: x,
        **where
    ):
        """
        Get the character memory context for a given character
        """

        memory_context = []
        for query in queries:
            i = 0
            for memory in await self.get(formatter(query), **where):
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


    @property
    def ready(self):
        if getattr(self, "db_client", None):
            return True
        return False

    @property
    def status(self):
        if self.ready:
            return "active" if not getattr(self, "processing", False) else "busy"
        return "waiting"

    @property
    def agent_details(self):
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

    async def set_db(self):
        await self.emit_status(processing=True)


        if not getattr(self, "db_client", None):
            log.info("chromadb agent", status="setting up db client to persistent db")
            self.db_client = chromadb.PersistentClient(
                settings=Settings(anonymized_telemetry=False)
            )

        openai_key = self.config.get("openai").get("api_key") or os.environ.get("OPENAI_API_KEY")
        
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
            
            self.db = self.db_client.get_or_create_collection(
                collection_name, embedding_function=ef
            )
        else:
            log.info("chromadb", status="using default embeddings")
            self.db = self.db_client.get_or_create_collection(collection_name)
        
        self.scene._memory_never_persisted = self.db.count() == 0

        await self.emit_status(processing=False)
        log.info("chromadb agent", status="db ready")

    def clear_db(self):
        if not self.db:
            return
        
        log.info("chromadb agent", status="clearing db", collection_name=self.collection_name)
        
        self.db.delete(where={"source": "talemate"})

    def close_db(self, scene):
        if not self.db:
            return
        
        log.info("chromadb agent", status="closing db", collection_name=self.collection_name)
        
        if not scene.saved:
            # scene was never saved so we can discard the memory
            collection_name = self.make_collection_name(scene)
            log.info("chromadb agent", status="discarding memory", collection_name=collection_name)
            self.db_client.delete_collection(collection_name)
        
        self.db = None
        
    async def _add(self, text, character=None, uid=None, ts:str=None, **kwargs):
        metadatas = []
        ids = []

        await self.emit_status(processing=True)

        if character:
            meta = {"character": character.name, "source": "talemate"}
            if ts:
                meta["ts"] = ts
            meta.update(kwargs)
            metadatas.append(meta)
            self.memory_tracker.setdefault(character.name, 0)
            self.memory_tracker[character.name] += 1
            id = uid or f"{character.name}-{self.memory_tracker[character.name]}"
            ids = [id]
        else:
            meta = {"character": "__narrator__", "source": "talemate"}
            if ts:
                meta["ts"] = ts
            meta.update(kwargs)
            metadatas.append(meta)
            self.memory_tracker.setdefault("__narrator__", 0)
            self.memory_tracker["__narrator__"] += 1
            id = uid or f"__narrator__-{self.memory_tracker['__narrator__']}"
            ids = [id]

        log.debug("chromadb agent add", text=text, meta=meta, id=id)

        self.db.upsert(documents=[text], metadatas=metadatas, ids=ids)
        
        await self.emit_status(processing=False)

    async def _add_many(self, objects: list[dict]):
        
        documents = []
        metadatas = []
        ids = []

        await self.emit_status(processing=True)

        for obj in objects:
            documents.append(obj["text"])
            meta = obj.get("meta", {})
            character = meta.get("character", "__narrator__")
            self.memory_tracker.setdefault(character, 0)
            self.memory_tracker[character] += 1
            meta["source"] = "talemate"
            metadatas.append(meta)
            uid = obj.get("id", f"{character}-{self.memory_tracker[character]}")
            ids.append(uid)
        self.db.upsert(documents=documents, metadatas=metadatas, ids=ids)

        await self.emit_status(processing=False)

    async def _get(self, text, character=None, **kwargs):
        await self.emit_status(processing=True)

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

        _results = self.db.query(query_texts=[text], where=where)
        
        results = []

        for i in range(len(_results["distances"][0])):
            distance = _results["distances"][0][i]
            
            doc = _results["documents"][0][i]
            meta = _results["metadatas"][0][i]
            ts = meta.get("ts")
            
            if distance < 1:
                
                try:
                    date_prefix = util.iso8601_diff_to_human(ts, self.scene.ts)
                except Exception:
                    log.error("chromadb agent", error="failed to get date prefix", ts=ts, scene_ts=self.scene.ts)
                    date_prefix = None
                    
                if date_prefix:
                    doc = f"{date_prefix}: {doc}"
                results.append(doc)
            else:
                break

            # log.debug("crhomadb agent get", result=results[-1], distance=distance)

            if len(results) > 10:
                break

        await self.emit_status(processing=False)

        return results
