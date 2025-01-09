from typing import TYPE_CHECKING
import structlog
from talemate.agents.base import (
    set_processing,
    AgentAction,
    AgentActionConfig
)
from talemate.prompts import Prompt
from talemate.emit import emit
from talemate.instance import get_agent
import talemate.emit.async_signals
from talemate.agents.conversation import ConversationAgentEmission
import talemate.game.focal as focal
from talemate.scene_message import ContextInvestigationMessage

if TYPE_CHECKING:
    from talemate.tale_mate import Scene, Character

log = structlog.get_logger()

class GuideSceneMixin:
    
    """
    Director agent mixin that provides functionality for automatically guiding
    the actors or the narrator during the scene progression.
    """
    
    @classmethod
    def add_actions(cls, director):
        director.actions["guide_scene"] = AgentAction(
            enabled=False,
            container=True,
            can_be_disabled=True,
            experimental=True,
            label="Guide Scene",
            icon="mdi-lightbulb",
            description="Analyzes the scene and provides guidance to the actors or the narrator.",
            config={
                "guide_actors": AgentActionConfig(
                    type="bool",
                    label="Guide actors",
                    description="Whether to guide the actors in the scene. This happens during every actor turn.",
                    value=True
                ),
            }
        )
    
    # config property helpers
        
    @property
    def guide_scene(self) -> bool:
        return self.actions["guide_scene"].enabled
    
    @property
    def guide_actors(self) -> bool:
        return self.actions["guide_scene"].config["guide_actors"].value