"""
Shared canned client-level responses for the character-creation test files
(test_creator_character.py, test_director_character_management.py,
test_character_card_extraction_options.py).

The tests mock at the last hop — the client response level (MockClient +
client_responses queue) — so real templates render and real
extraction/parsing runs. Each builder here produces a response that the
corresponding *real* production method can parse:

- several templates prepare part of the response via
  ``set_prepared_response`` and ``Prompt.send`` prepends it when the client
  response doesn't already start with it, so canned responses must begin
  with the prepared text (see the individual builders)
- the response queue is order-coupled by design: generation order is
  behavior, and the tests assert it via ``MockClient.prompt_history`` kinds
"""

import json

# prompt kinds per real request path, for routing assertions against
# MockClient.prompt_history (see the corresponding Prompt.request calls)
KIND_NAME = "analyze_freeform_24"  # creator.determine-character-name
KIND_DESCRIPTION = "create"  # creator.determine-character-description
KIND_DIALOGUE_INSTRUCTIONS = "create_concise"  # ...-dialogue-instructions
KIND_SHEET = "create"  # world_state.extract-character-sheet
KIND_FOCAL = "analyze_1024"  # focal.request default response_length
KIND_UNIFIED = "create_4096"  # creator.generate-character @ default budget

# the character_creation "Consolidate" config default (for restoring after
# tests that widen or narrow the selection): every aspect, plus the
# 'Attribute templates' fold flag
DEFAULT_CONSOLIDATE = [
    "name",
    "description",
    "attributes",
    "dialogue_instructions",
    "example_dialogue",
    "attribute_templates",
]


def prompt_kinds(client) -> list[str]:
    """The kinds of all prompts the MockClient received, in order."""
    return [entry["kind"] for entry in client.prompt_history]


def unified_response(
    name=None,
    description=None,
    attributes=None,
    dialogue_instructions=None,
    example_dialogue=None,
) -> str:
    """Consolidated one-shot response: closed <TAG> sections per aspect
    (StrictAnchorExtractor only accepts complete blocks)."""
    parts = []
    if name is not None:
        parts.append(f"<NAME>{name}</NAME>")
    if description is not None:
        parts.append(f"<DESCRIPTION>{description}</DESCRIPTION>")
    if attributes is not None:
        parts.append(f"<ATTRIBUTES>{attributes}</ATTRIBUTES>")
    if dialogue_instructions is not None:
        parts.append(
            f"<DIALOGUE_INSTRUCTIONS>{dialogue_instructions}</DIALOGUE_INSTRUCTIONS>"
        )
    if example_dialogue is not None:
        parts.append(f"<EXAMPLE_DIALOGUE>{example_dialogue}</EXAMPLE_DIALOGUE>")
    return "\n".join(parts)


def name_response(name: str = "Elena") -> str:
    """determine_character_name response (NAME_SPEC anchor extraction)."""
    return f"<NAME>{name}</NAME>"


def description_response(
    name: str = "Elena", rest: str = "is a skilled healer."
) -> str:
    """determine_character_description response. The template prepares the
    response with the character's name, so the canned text must start with
    it (otherwise Prompt.send prepends it and the description mutates)."""
    return f"{name} {rest}"


def sheet_response(
    name: str = "Elena", attributes: dict[str, str] | None = None
) -> str:
    """world_state.extract_character_sheet response: attribute lines. The
    template prepares ``Name: <name>\\nAge:`` so the canned response must
    start exactly with that block; ``Name`` therefore always parses as the
    first attribute (production behavior)."""
    attributes = dict(
        attributes if attributes is not None else {"Occupation": "healer"}
    )
    lines = [f"Name: {name}", f"Age: {attributes.pop('Age', '30')}"]
    lines.extend(f"{key}: {value}" for key, value in attributes.items())
    return "\n".join(lines)


def focal_call_block(function: str, **arguments) -> str:
    """A focal-driven response: fenced JSON call block invoking one of the
    registered callbacks (e.g. add_dialogue_example)."""
    call = json.dumps({"function": function, "arguments": arguments})
    return f"```json\n{call}\n```"


def example_dialogue_response(example: str) -> str:
    """determine_character_dialogue_examples response: one
    add_dialogue_example focal call. The callback prefixes the character
    name when the example doesn't already carry it."""
    return focal_call_block("add_dialogue_example", example=example)
