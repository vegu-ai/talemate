"""
Shared helper functions for prompt template tests.

These utilities enable unit testing of Jinja2 templates with mocked objects,
without requiring an LLM connection.
"""

from unittest.mock import Mock
from talemate.prompts.base import Prompt


def create_mock_scene(
    context: str = "Fantasy adventure story",
    description: str = "A peaceful clearing in the heart of an ancient forest.",
    intro: str = "You find yourself in a quiet forest clearing.",
    outline: str = "A meeting between travelers in the forest.",
    title: str = "The Forest Clearing",
    history: list = None,
) -> Mock:
    """
    Create a minimal mock scene for template testing.

    Args:
        context: Scene content classification/genre
        description: Scene description
        intro: Scene intro text
        outline: Scene outline
        title: Scene title
        history: Optional list of history entries

    Returns:
        Mock scene object with all required attributes for template rendering
    """
    scene = Mock()
    scene.context = context
    scene.description = description
    scene.intro = intro
    scene.outline = outline
    scene.title = title
    scene.ts = "PT2H30M"
    scene.environment = "scene"
    scene.history = history or []
    scene.archived_history = []
    scene.active_pins = []

    # Mock methods
    scene.context_history = Mock(return_value=[
        "Elena: Hello there, traveler.",
        "The sun filters through the leaves above.",
        "Marcus: What brings you to these woods?"
    ])
    scene.last_message_of_type = Mock(return_value="Elena: Hello there, traveler.")
    scene.get_characters = Mock(return_value=[])
    scene.num_history_entries = 3

    # Characters list (for templates that iterate over scene.characters)
    scene.characters = []

    # World state
    scene.world_state = Mock()
    scene.world_state.filter_reinforcements = Mock(return_value=[])
    scene.world_state.description = "A fantastical medieval world"

    # Game state
    scene.game_state = Mock()
    scene.game_state.state = {}

    return scene


def create_mock_agent(agent_type: str = "narrator") -> Mock:
    """
    Create a minimal mock agent for template testing.

    Args:
        agent_type: The type of agent (narrator, director, etc.)

    Returns:
        Mock agent object with required attributes
    """
    agent = Mock()
    agent.state = {}
    agent.agent_type = agent_type
    agent.client = Mock()
    agent.client.max_token_length = 4096
    agent.client.decensor_enabled = False
    agent.client.can_be_coerced = True
    return agent


def create_mock_character(
    name: str = "Elena",
    is_player: bool = False,
    gender: str = "female",
    description: str = "A wandering healer with knowledge of ancient herbs.",
) -> Mock:
    """
    Create a minimal mock character for template testing.

    Args:
        name: Character name
        is_player: Whether this is a player character
        gender: Character gender
        description: Character description

    Returns:
        Mock character object with required attributes
    """
    char = Mock()
    char.name = name
    char.description = description
    char.is_player = is_player
    char.gender = gender
    char.greeting_text = "Hello there, traveler."
    char.dialogue_instructions = "Speaks calmly and with wisdom."
    char.base_attributes = {
        "name": name,
        "gender": gender,
        "age": "early 30s",
        "occupation": "Healer" if not is_player else "Adventurer"
    }
    char.details = {
        "background": "Trained by forest hermits from a young age."
    }
    char.sheet = f"name: {name}\ngender: {gender}\nage: early 30s"
    char.example_dialogue = [f"{name}: The forest provides all we need."]
    char.random_dialogue_example = f"{name}: The forest provides all we need."
    return char


def create_base_context(
    scene: Mock = None,
    max_tokens: int = 4096,
    extra_instructions: str = "",
    technical: bool = False,
    decensor: bool = False,
) -> dict:
    """
    Create a base context dict for template rendering.

    Args:
        scene: Mock scene (created if not provided)
        max_tokens: Token budget
        extra_instructions: Additional instructions for the template
        technical: Whether to use technical mode
        decensor: Whether decensor is enabled

    Returns:
        Dict with common template variables
    """
    return {
        "scene": scene or create_mock_scene(),
        "max_tokens": max_tokens,
        "extra_instructions": extra_instructions,
        "technical": technical,
        "decensor": decensor,
    }


def render_template(uid: str, vars: dict = None, client=None) -> str:
    """
    Helper to render a template with optional variables.

    Args:
        uid: Template UID in format "agent.template_name"
        vars: Template variables
        client: Optional mock client

    Returns:
        Rendered template string
    """
    prompt = Prompt.get(uid, vars=vars or {})
    if client:
        prompt.client = client
    return prompt.render()


def assert_template_renders(uid: str, vars: dict = None, client=None):
    """
    Assert that a template renders without Jinja2 errors.

    Args:
        uid: Template UID in format "agent.template_name"
        vars: Template variables
        client: Optional mock client

    Raises:
        AssertionError: If template fails to render
    """
    result = render_template(uid, vars, client)
    assert result is not None, f"Template {uid} rendered to None"
    assert len(result) > 0, f"Template {uid} rendered to empty string"


def assert_has_bot_token(uid: str, vars: dict = None, client=None):
    """
    Assert that a template uses set_prepared_response (contains <|BOT|>).

    Templates that use set_prepared_response() will have the <|BOT|> marker
    in their rendered output, indicating they expect to coerce the LLM response.
    """
    result = render_template(uid, vars, client)
    prompt = Prompt.get(uid, vars=vars or {})
    if client:
        prompt.client = client
    prompt.render()

    has_bot_token = "<|BOT|>" in result or prompt.prepared_response
    assert has_bot_token, f"Template {uid} does not use set_prepared_response"


def assert_has_data_response(uid: str, vars: dict = None, client=None):
    """
    Assert that a template uses set_data_response.

    Templates that use set_data_response() will have data_response=True
    set on the prompt after rendering.
    """
    prompt = Prompt.get(uid, vars=vars or {})
    if client:
        prompt.client = client
    prompt.render()

    assert prompt.data_response, f"Template {uid} does not use set_data_response"
