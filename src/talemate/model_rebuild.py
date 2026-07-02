"""
Resolve forward refs on pydantic models that reference Actor/Scene/Character.

These models live in modules that import ``talemate.tale_mate`` (or
``talemate.character``) only under ``TYPE_CHECKING`` to avoid circular imports
at load time. Pydantic v2 cannot resolve those forward refs until the real
types are in scope — so we collect every affected model here and call
``model_rebuild()`` in one place, after ``tale_mate`` has finished loading.

Import this module from ``talemate.__init__`` after ``tale_mate``.
"""

# Concrete types that the forward refs point to. Importing them here puts
# them in this module's globals, but ``model_rebuild()`` resolves names from
# the model's own defining module — so we also hand them in explicitly via
# ``_types_namespace``.
from talemate.character import Character
from talemate.game.engine.context_id.character import (
    CharacterContext,
    CharacterContextItem,
)
from talemate.scene_message import SceneMessage
from talemate.tale_mate import Actor, Scene

from talemate.emit.base import Emission
from talemate.events import (
    ArchiveEvent,
    CharacterStateEvent,
    Event,
    GameLoopActorIterEvent,
    GameLoopBase,
    GameLoopCharacterIterEvent,
    GameLoopEvent,
    GameLoopNewMessageEvent,
    GameLoopStartEvent,
    HistoryEvent,
    PlayerTurnStartEvent,
    RegenerateGeneration,
    SceneStateEvent,
)
from talemate.game.engine.nodes.scene import SceneLoopEvent
from talemate.agents.conversation import ConversationAgentEmission
from talemate.agents.creator.assistant import (
    AutocompleteEmission,
    ContextualGenerateEmission,
)
from talemate.agents.director.character_management import PersistCharacterEmission
from talemate.agents.director.generate_choices import GenerateChoicesEmission
from talemate.agents.summarize.analyze_scene import SceneAnalysisDeepAnalysisEmission

_TYPES = {
    "Actor": Actor,
    "Character": Character,
    "Scene": Scene,
    "SceneMessage": SceneMessage,
}

for _model in (
    Character,
    CharacterContextItem,
    CharacterContext,
    Emission,
    Event,
    HistoryEvent,
    ArchiveEvent,
    CharacterStateEvent,
    SceneStateEvent,
    GameLoopBase,
    GameLoopEvent,
    GameLoopStartEvent,
    GameLoopActorIterEvent,
    GameLoopCharacterIterEvent,
    GameLoopNewMessageEvent,
    PlayerTurnStartEvent,
    RegenerateGeneration,
    SceneLoopEvent,
    ConversationAgentEmission,
    ContextualGenerateEmission,
    AutocompleteEmission,
    PersistCharacterEmission,
    GenerateChoicesEmission,
    SceneAnalysisDeepAnalysisEmission,
):
    _model.model_rebuild(_types_namespace=_TYPES)
