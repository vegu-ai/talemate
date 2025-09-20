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

log = structlog.get_logger("talemate.game.engine.nodes.agents.memory")

TYPE_CHOICES.extend(
    [
        "memory/document",
    ]
)


@register("agents/memory/QueryContextDB")
class QueryContextDB(AgentNode):
    """
    Node that queries the context database

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

        results = await self.agent.multi_query(
            queries,
            iterate=iterate,
            max_tokens=max_tokens,
            filter=fn_filter,
            formatter=fn_formatter,
            limit=limit,
            **meta_filters,
        )
        self.set_output_values({"state": state, "results": results})


@register("agents/memory/UnpackMemoryDocument")
class UnpackMemoryDocument(Node):
    """
    Unpacks a memory document
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
