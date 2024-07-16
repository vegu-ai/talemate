from __future__ import annotations

import json
import os

import talemate.client as client
from talemate.agents.base import Agent, set_processing
from talemate.agents.registry import register
from talemate.emit import emit
from talemate.prompts import Prompt

from .assistant import AssistantMixin
from .character import CharacterCreatorMixin
from .legacy import LegacyCharacterCreatorMixin, LegacyScenarioCreatorMixin
from .scenario import ScenarioCreatorMixin


@register()
class CreatorAgent(
    LegacyScenarioCreatorMixin,
    LegacyCharacterCreatorMixin,
    CharacterCreatorMixin,
    ScenarioCreatorMixin,
    AssistantMixin,
    Agent,
):
    """
    Creates characters and scenarios and other fun stuff!
    """

    agent_type = "creator"
    verbose_name = "Creator"

    def __init__(
        self,
        client: client.TaleMateClient,
        **kwargs,
    ):
        self.client = client

    def clean_result(self, result):
        if "#" in result:
            result = result.split("#")[0]

        return result

    def load_templates(self, names: list, template_type: str = "character") -> dict:
        """
        Loads multiple character creation templates from ./templates/character and merges them in order.
        Also loads instructions if present in the template.

        Args:
            names (list): A list of template file names without the extension.
            template_type (str, optional): The type of template to load. Defaults to "character".
        Returns:
            dict: A dictionary containing merged properties based on their type.
        """
        merged_data = {}
        context = "unknown"

        for template_index, name in enumerate(names):
            template_path = os.path.join("./templates", template_type, f"{name}.json")

            if not os.path.exists(template_path):
                raise Exception(f"Template {template_path} does not exist.")

            with open(template_path, "r") as f:
                template_data = json.load(f)

            # Merge all keys at the root label based on their type
            for key, value in template_data.items():
                if isinstance(value, list):
                    if key not in merged_data:
                        merged_data[key] = []
                    for item in value:
                        if isinstance(item, list):
                            merged_data[key] += [(item[0], item[1], name)]
                        else:
                            merged_data[key] += [(item, name)]
                elif isinstance(value, dict):
                    if key not in merged_data:
                        merged_data[key] = {}
                    merged_data[key][name] = value
                    if "context" in value:
                        context = value["context"]

        # Remove duplicates while preserving the order for list type keys
        for key, value in merged_data.items():
            if isinstance(value, list):
                merged_data[key] = [
                    x for i, x in enumerate(value) if x not in value[:i]
                ]

        merged_data["context"] = context

        return merged_data

    def load_templates_old(self, names: list, template_type: str = "character") -> dict:
        """
        Loads multiple character creation templates from ./templates/character and merges them in order.
        Also loads instructions if present in the template.

        Args:
            names (list): A list of template file names without the extension.
            template_type (str, optional): The type of template to load. Defaults to "character".
        Returns:
            dict: A dictionary containing merged 'template', 'questions', 'history_prompts', and 'instructions' properties.
        """
        merged_template = []
        merged_questions = []
        merged_history_prompts = []
        merged_spice = []
        merged_instructions = {}

        context = "unknown"

        for template_index, name in enumerate(names):
            template_path = os.path.join("./templates", template_type, f"{name}.json")

            if not os.path.exists(template_path):
                raise Exception(f"Template {template_path} does not exist.")

            with open(template_path, "r") as f:
                template_data = json.load(f)

            # Merge the template, questions, history_prompts, and instructions properties with their original order
            merged_template += [
                (item, name) for item in template_data.get("template", [])
            ]
            merged_questions += [
                (item[0], item[1], name) for item in template_data.get("questions", [])
            ]
            merged_history_prompts += [
                (item, name) for item in template_data.get("history_prompts", [])
            ]
            merged_spice += [(item, name) for item in template_data.get("spice", [])]
            if "instructions" in template_data:
                merged_instructions[name] = template_data["instructions"]

                if "context" in template_data["instructions"]:
                    context = template_data["instructions"]["context"]

                merged_instructions[name]["questions"] = [
                    q[0] for q in template_data.get("questions", [])
                ]

        # Remove duplicates while preserving the order
        merged_template = [
            x for i, x in enumerate(merged_template) if x not in merged_template[:i]
        ]
        merged_questions = [
            x for i, x in enumerate(merged_questions) if x not in merged_questions[:i]
        ]
        merged_history_prompts = [
            x
            for i, x in enumerate(merged_history_prompts)
            if x not in merged_history_prompts[:i]
        ]
        merged_spice = [
            x for i, x in enumerate(merged_spice) if x not in merged_spice[:i]
        ]

        rv = {
            "template": merged_template,
            "questions": merged_questions,
            "history_prompts": merged_history_prompts,
            "instructions": merged_instructions,
            "spice": merged_spice,
            "context": context,
        }

        return rv

    @set_processing
    async def generate_json_list(
        self,
        text: str,
        count: int = 20,
        first_item: str = None,
    ):
        _, json_list = await Prompt.request(
            f"creator.generate-json-list",
            self.client,
            "create",
            vars={
                "text": text,
                "first_item": first_item,
                "count": count,
            },
        )
        return json_list.get("items", [])

    @set_processing
    async def generate_title(self, text: str):
        title = await Prompt.request(
            f"creator.generate-title",
            self.client,
            "create_short",
            vars={
                "text": text,
            },
        )
        return title
