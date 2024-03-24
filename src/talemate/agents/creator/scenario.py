import random
import re

from talemate.agents.base import set_processing
from talemate.emit import emit, wait_for_input_yesno
from talemate.prompts import Prompt


class ScenarioCreatorMixin:
    """
    Adds scenario creation functionality to the creator agent
    """

    @set_processing
    async def create_scene_description(
        self,
        prompt: str,
        content_context: str,
    ):
        """
        Creates a new scene.

        Arguments:

            prompt (str): The prompt to use to create the scene.

            content_context (str): The content context to use for the scene.

            callback (callable): A callback to call when the scene has been created.
        """
        scene = self.scene

        description = await Prompt.request(
            "creator.scenario-description",
            self.client,
            "create",
            vars={
                "prompt": prompt,
                "content_context": content_context,
                "max_tokens": self.client.max_token_length,
                "scene": scene,
            },
        )
        description = description.strip()

        return description

    @set_processing
    async def create_scene_name(
        self,
        prompt: str,
        content_context: str,
        description: str,
    ):
        """
        Generates a scene name.

        Arguments:

            prompt (str): The prompt to use to generate the scene name.

            content_context (str): The content context to use for the scene.

            description (str): The description of the scene.
        """
        scene = self.scene

        name = await Prompt.request(
            "creator.scenario-name",
            self.client,
            "create",
            vars={
                "prompt": prompt,
                "content_context": content_context,
                "description": description,
                "scene": scene,
            },
        )
        name = name.strip().strip(".!").replace('"', "")
        return name

    @set_processing
    async def create_scene_intro(
        self,
        prompt: str,
        content_context: str,
        description: str,
        name: str,
    ):
        """
        Generates a scene introduction.

        Arguments:

            prompt (str): The prompt to use to generate the scene introduction.

            content_context (str): The content context to use for the scene.

            description (str): The description of the scene.

            name (str): The name of the scene.
        """

        scene = self.scene

        intro = await Prompt.request(
            "creator.scenario-intro",
            self.client,
            "create",
            vars={
                "prompt": prompt,
                "content_context": content_context,
                "description": description,
                "name": name,
                "scene": scene,
            },
        )
        intro = intro.strip()
        return intro

    @set_processing
    async def determine_scenario_description(self, text: str):
        description = await Prompt.request(
            f"creator.determine-scenario-description",
            self.client,
            "analyze_long",
            vars={
                "text": text,
            },
        )
        return description


    @set_processing
    async def determine_content_context_for_description(
        self,
        description:str,
    ):
        content_context = await Prompt.request(
            f"creator.determine-content-context",
            self.client,
            "create",
            vars={
                "description": description,
            },
        )
        return content_context.strip()