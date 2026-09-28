import structlog
from typing import ClassVar, Callable
from talemate.game.engine.nodes.core import (
    Node,
    GraphState,
    PropertyField,
    InputValueError,
    TYPE_CHOICES,
)
from talemate.game.engine.nodes.registry import register
from talemate.game.engine.nodes.agent import AgentNode
from talemate.game.engine.nodes.run import FunctionWrapper

from talemate.agents.memory.schema import MemoryDocument
from talemate.context import active_scene
from talemate.decisions.characters import character_named, referenced_characters
from talemate.agents.memory.rag import knowledge_retrieval_filter
from talemate.character import character_name
from talemate.knowledge.mode import character_knowledge_enabled

log = structlog.get_logger("talemate.game.engine.nodes.agents.memory")

TYPE_CHOICES.extend(
    [
        "memory/document",
    ]
)


@register("agents/memory/QueryContextDB")
class QueryContextDB(AgentNode):
    """
    Queries the memory agent's context database with one or more queries
    and collects the matching documents, up to a total token budget.

    Inputs:

    - state: The graph state
    - queries: The queries to run (list, or a single query string)
    - meta_filters: Metadata filters to constrain the results (optional)
    - max_tokens: The maximum total tokens of results to return (optional)
    - fn_filter: Function that receives a result and returns whether to
      keep it (optional)
    - fn_formatter: Function that receives a result and returns its
      formatted replacement (optional)
    - viewer: Return only what this character knows (optional). With
      Character Perspectives on, results come from the character's own
      memories; otherwise entries the character does not know are left out.

    Properties:

    - iterate: The number of results to accept per query
    - limit: The number of N best results to consider per query

    Outputs:

    - state: The state input, passed through
    - results: The list of matching documents
    """

    _agent_name: ClassVar[str] = "memory"

    class Fields:
        queries = PropertyField(
            name="queries",
            description="The queries to use to query the context database",
            type="list",
            default=[],
        )
        iterate = PropertyField(
            name="iterate",
            description="The number of results to return per query",
            type="int",
            default=3,
        )
        max_tokens = PropertyField(
            name="max_tokens",
            description="The maximum number of tokens to return",
            type="int",
            default=1024,
        )
        limit = PropertyField(
            name="limit",
            description="The number of N best results to consider per query",
            type="int",
            default=10,
        )
        meta_filters = PropertyField(
            name="meta_filters",
            description="The meta filters to apply to the results",
            type="dict",
            default={},
        )

    def __init__(self, title="Query Context DB", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("queries", socket_type="list,str", optional=True)
        self.add_input("meta_filters", socket_type="dict", optional=True)
        self.add_input("max_tokens", socket_type="int", optional=True)
        self.add_input("fn_filter", socket_type="function", optional=True)
        self.add_input("fn_formatter", socket_type="function", optional=True)
        self.add_input("viewer", socket_type="str,character", optional=True)
        self.set_property("queries", [])
        self.set_property("meta_filters", {})
        self.set_property("max_tokens", 1024)
        self.set_property("limit", 10)
        self.set_property("iterate", 3)

        self.add_output("state")
        self.add_output("results", socket_type="list")

    async def run(self, state: GraphState):
        queries: list[str] | str = self.require_input("queries")

        if isinstance(queries, str):
            queries = [queries]

        limit: int = self.require_number_input("limit")
        iterate: int = self.require_number_input("iterate")
        max_tokens: int = self.require_number_input("max_tokens")
        fn_filter: FunctionWrapper | None = self.normalized_input_value("fn_filter")
        fn_formatter: FunctionWrapper | None = self.normalized_input_value(
            "fn_formatter"
        )
        meta_filters: dict = self.normalized_input_value("meta_filters") or {}
        if fn_filter and not isinstance(fn_filter, FunctionWrapper):  # type: ignore
            raise InputValueError(self, "fn_filter", "fn_filter must be a function")
        if fn_formatter and not isinstance(fn_formatter, FunctionWrapper):  # type: ignore
            raise InputValueError(
                self, "fn_formatter", "fn_formatter must be a function"
            )

        # Function Wrapper __call__ is a coroutine, we need sync wrapper
        if fn_filter:
            fn_filter: Callable = fn_filter.sync_wrapper()
        else:

            def fn_filter(x):
                return True

        if fn_formatter:
            fn_formatter: Callable = fn_formatter.sync_wrapper()
        else:

            def fn_formatter(x):
                return x

        log.debug(
            "Querying context database",
            queries=queries,
            max_tokens=max_tokens,
            filter=fn_filter,
            formatter=fn_formatter,
            limit=limit,
            meta_filters=meta_filters,
        )

        viewer_kwargs = {}
        viewer = self.normalized_input_value("viewer")
        if viewer is not None:
            scene = active_scene.get()
            viewer = character_name(viewer)
            if viewer not in scene.character_data:
                raise InputValueError(
                    self, "viewer", f"Character `{viewer}` does not exist."
                )
            if character_knowledge_enabled(scene):
                viewer_kwargs["viewer"] = viewer
            else:
                knows = knowledge_retrieval_filter(scene, viewer)
                graph_filter = fn_filter

                def fn_filter(x):
                    return knows(x) and graph_filter(x)

                # the filter drops results after the vector search
                viewer_kwargs["over_fetch"] = 3

        results = await self.agent.multi_query(
            queries,
            iterate=iterate,
            max_tokens=max_tokens,
            filter=fn_filter,
            formatter=fn_formatter,
            limit=limit,
            **viewer_kwargs,
            **meta_filters,
        )
        self.set_output_values({"state": state, "results": results})


@register("agents/memory/ReferencedCharacters")
class ReferencedCharacters(AgentNode):
    """
    Which characters a text refers to, by name, by a mapped alias or, with
    the decision model, by pronoun, title or nickname ("her brother", "the
    Captain"). The candidates default to the characters not in the scene.

    Uses the memory agent's entity lookup setting "Use Decision Model" and the
    same editable decision policy; without a decision model, or when it is
    uncertain, names and aliases are matched in the text.

    Inputs:

    - state: graph state (passthrough)
    - text: the text to check
    - candidates: character names to check (optional)

    Outputs:

    - state: graph state
    - characters: the candidates the text refers to, in candidate order
    """

    _agent_name: ClassVar[str] = "memory"

    def __init__(self, title="Referenced Characters", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("text", socket_type="str")
        self.add_input("candidates", socket_type="list", optional=True)
        self.add_output("state")
        self.add_output("characters", socket_type="list")

    async def run(self, state: GraphState):
        scene = active_scene.get()
        text = self.require_input("text")
        candidates = self.normalized_input_value("candidates")
        if candidates is None:
            candidates = list(scene.inactive_characters)
        unknown = [name for name in candidates if name not in scene.character_data]
        if unknown:
            raise InputValueError(
                self, "candidates", f"Unknown characters: {', '.join(unknown)}"
            )
        characters = (
            await referenced_characters(
                scene,
                text,
                list(candidates),
                uid="memory.decision-entity-references",
                enabled=self.agent.retrieval_entity_decision_model,
                match=lambda name: character_named(scene, name, text),
            )
            if text.strip() and candidates
            else []
        )
        self.set_output_values(
            {"state": self.get_input_value("state"), "characters": characters}
        )


@register("agents/memory/UnpackMemoryDocument")
class UnpackMemoryDocument(Node):
    """
    Unpacks a memory document into its individual fields.

    Inputs:

    - document: The memory document to unpack

    Outputs:

    - document: The memory document, passed through
    - meta: The document's metadata dict
    - id: The document's ID in the memory database
    - raw: The document's raw content
    - as_text: The document rendered as text
    - as_dict: The document as a dict
    - context_id: The document's context ID
    """

    def __init__(self, title="Unpack Memory Document", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("document", socket_type="memory/document")
        self.add_output("document", socket_type="memory/document")
        self.add_output("meta", socket_type="dict")
        self.add_output("id", socket_type="str")
        self.add_output("raw", socket_type="dict")
        self.add_output("as_text", socket_type="str")
        self.add_output("as_dict", socket_type="dict")
        self.add_output("context_id", socket_type="context_id")

    async def run(self, state: GraphState):
        document: MemoryDocument = self.require_input("document")

        self.set_output_values(
            {
                "document": document,
                "meta": document.meta,
                "id": document.id,
                "raw": document.raw,
                "as_text": str(document),
                "as_dict": document.__dict__(),
                "context_id": document.context_id,
            }
        )
