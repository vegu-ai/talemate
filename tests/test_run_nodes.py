import pytest
from talemate.game.engine.nodes.core import (
    Node, Graph, GraphState, GraphContext, 
    Socket, UNRESOLVED
)
from talemate.game.engine.nodes.run import (
    FunctionArgument, FunctionReturn, FunctionWrapper
)