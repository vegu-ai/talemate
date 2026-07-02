"""
Real-object helpers for prompt template tests.

These helpers build actual Scene, Character, Actor, WorldState, and GameState
instances rather than Mocks, so template tests fail loudly when the
underlying schemas change.

LLM clients and most agents remain stubbed — they reach out to real
infrastructure (network, filesystem) which template tests must not touch.
"""

from typing import Iterable
from unittest.mock import Mock

import talemate.instance as instance
from talemate.character import Character
from talemate.prompts.base import Prompt
from talemate.tale_mate import Actor, Player, Scene
from talemate.world_state import CharacterState, ObjectState, PlaceState


# Default rendered-history lines returned by ``Scene.context_history``. The real
# method delegates to the summarizer agent, which pulls the LLM; template tests
# just need a plausible iterable of strings.
DEFAULT_CONTEXT_HISTORY = [
    "Elena: Hello there, traveler.",
    "The sun filters through the leaves above.",
    "Marcus: What brings you to these woods?",
]


class MockScene(Scene):
    """``Scene`` subclass with a writable ``writing_style`` for template tests.

    The real ``Scene.writing_style`` is a read-only property that resolves
    through the world-state template collection — that path requires a fully
    wired scene on disk, which template tests don't have. Overriding the
    property here lets tests set a truthy sentinel (string or template stub)
    so templates that gate on ``scene.writing_style`` can render their
    branches.
    """

    @property
    def writing_style(self):
        return getattr(self, "_mock_writing_style", None)

    @writing_style.setter
    def writing_style(self, value):
        self._mock_writing_style = value

    @property
    def template_dir(self):
        # Default: real property's value (``save_dir/templates``) — most tests
        # don't need a real directory. Tests that load Jinja2 templates from
        # disk can set an override via ``scene.template_dir = ...``.
        if hasattr(self, "_mock_template_dir"):
            return self._mock_template_dir
        return super().template_dir  # type: ignore[misc]

    @template_dir.setter
    def template_dir(self, value):
        self._mock_template_dir = value


def create_mock_scene(
    context: str = "Fantasy adventure story",
    description: str = "A peaceful clearing in the heart of an ancient forest.",
    intro: str = "You find yourself in a quiet forest clearing.",
    outline: str = "A meeting between travelers in the forest.",
    title: str = "The Forest Clearing",
    history: list | None = None,
) -> Scene:
    """Create a real Scene, lightly populated with the scalar fields templates read.

    The returned scene has a real ``WorldState`` / ``GameState`` / ``SceneIntent``
    attached via ``Scene.__init__``. ``context_history`` and ``last_message_of_type``
    are stubbed with canned return values because their real implementations call
    into the summarizer agent (which tests don't want to spin up). No actors are
    added by default — use :func:`add_character` or :func:`create_scene_with_characters`
    to populate.
    """
    scene = MockScene()
    scene.context = context
    scene.description = description
    scene.intro = intro
    scene.outline = outline
    scene.title = title
    scene.ts = "PT2H30M"
    scene.environment = "scene"
    # Default narrative perspective so templates gated on
    # ``scene.perspectives.default`` render their branches. Tests that want the
    # section suppressed can set ``scene.perspectives.default = ""``.
    scene.perspectives.default = "Third person limited, past tense."
    if history:
        scene.history = list(history)

    # These delegate to the summarizer agent in production — stub them so
    # template tests don't need a fully-wired agent registry.
    scene.context_history = Mock(return_value=list(DEFAULT_CONTEXT_HISTORY))
    scene.last_message_of_type = Mock(return_value="Elena: Hello there, traveler.")

    # Default SceneIntent has a prefilled "roleplay" phase — zero it out so
    # the "Intention of the current scene" section stays empty unless a test
    # explicitly configures phase/intent. Tests that need intent rendering can
    # set ``scene.intent_state.phase`` / ``.intent`` themselves.
    scene.intent_state.phase = None
    return scene


def create_mock_character(
    name: str = "Elena",
    is_player: bool = False,
    gender: str = "female",
    description: str = "A wandering healer with knowledge of ancient herbs.",
) -> Character:
    """Create a real ``Character`` with sensible defaults for template tests."""
    return Character(
        name=name,
        is_player=is_player,
        description=description,
        greeting_text="Hello there, traveler.",
        dialogue_instructions="Speaks calmly and with wisdom.",
        base_attributes={
            "name": name,
            "gender": gender,
            "age": "early 30s",
            "occupation": "Adventurer" if is_player else "Healer",
        },
        details={"background": "Trained by forest hermits from a young age."},
        example_dialogue=[f"{name}: The forest provides all we need."],
    )


def add_character(scene: Scene, character: Character, agent=None) -> Actor:
    """Attach a ``Character`` to a ``Scene`` as an active ``Actor`` / ``Player``.

    Mirrors what ``Scene.add_actor`` does without requiring a real memory agent.
    """
    actor_cls = Player if character.is_player else Actor
    actor = actor_cls(character=character, agent=agent)
    scene.actors.append(actor)
    scene.character_data[character.name] = character
    if character.name not in scene.active_characters:
        scene.active_characters.append(character.name)
    actor.scene = scene
    return actor


def create_scene_with_characters(
    characters: Iterable[Character] | None = None,
    **scene_kwargs,
) -> Scene:
    """Build a scene and register the given characters as active actors.

    When ``characters`` is None, registers a default Hero (player) +
    Elena (NPC) pair.
    """
    scene = create_mock_scene(**scene_kwargs)
    if characters is None:
        characters = [
            create_mock_character(name="Hero", is_player=True, gender="male"),
            create_mock_character(name="Elena", is_player=False, gender="female"),
        ]
    for character in characters:
        add_character(scene, character)
    return scene


def create_mock_agent(agent_type: str = "narrator") -> Mock:
    """Minimal stub agent for templates that need an ``agent`` variable.

    Agents talk to LLMs in production; template tests use a stub that only
    exposes the attributes templates actually read.
    """
    agent = Mock()
    agent.state = {}
    agent.agent_type = agent_type
    agent.client = Mock()
    agent.client.max_token_length = 4096
    agent.client.decensor_enabled = False
    agent.client.can_be_coerced = True
    return agent


def create_base_context(
    scene: Scene | None = None,
    max_tokens: int = 4096,
    extra_instructions: str = "",
    technical: bool = False,
    decensor: bool = False,
) -> dict:
    """Create a base context dict for template rendering."""
    return {
        "scene": scene if scene is not None else create_mock_scene(),
        "max_tokens": max_tokens,
        "extra_instructions": extra_instructions,
        "technical": technical,
        "decensor": decensor,
    }


def render_template(uid: str, vars: dict | None = None, client=None) -> str:
    """Render a template and return the rendered string."""
    prompt = Prompt.get(uid, vars=vars or {})
    if client:
        prompt.client = client
    return prompt.render()


def assert_template_renders(uid: str, vars: dict | None = None, client=None):
    """Assert that a template renders to a non-empty string."""
    result = render_template(uid, vars, client)
    assert result is not None, f"Template {uid} rendered to None"
    assert len(result) > 0, f"Template {uid} rendered to empty string"


def assert_has_bot_token(uid: str, vars: dict | None = None, client=None):
    """Assert that a template uses ``set_prepared_response`` (emits <|BOT|>)."""
    result = render_template(uid, vars, client)
    prompt = Prompt.get(uid, vars=vars or {})
    if client:
        prompt.client = client
    prompt.render()

    has_bot_token = "<|BOT|>" in result or prompt.prepared_response
    assert has_bot_token, f"Template {uid} does not use set_prepared_response"


def assert_has_data_response(uid: str, vars: dict | None = None, client=None):
    """Assert that a template uses ``set_data_response``."""
    prompt = Prompt.get(uid, vars=vars or {})
    if client:
        prompt.client = client
    prompt.render()

    assert prompt.data_response, f"Template {uid} does not use set_data_response"


def register_world_state_toggle(value: bool):
    """Register a minimal world_state agent whose snapshot toggle resolves to ``value``.

    ``agent_config("world_state.update_world_state.inject_as_scene_memory")`` calls
    ``instance.get_agent("world_state").resolve_config(...)``; this stands in for a
    real agent so the gate inside ``common/world-state-snapshot.jinja2`` can be
    exercised. Only assigns the registry entry — teardown (e.g. the ``setup_agents``
    fixture, or an explicit save/restore) is the caller's responsibility.
    """
    ws = Mock()
    ws.resolve_config = Mock(return_value=value)
    instance.AGENTS["world_state"] = ws
    return ws


def seed_world_state_snapshot(scene):
    """Populate the scene's durable world-state snapshot with one of each entity kind.

    Includes a character with an emotion, an item, a place, and a location so the
    rendered SCENE NOTES block exercises every branch of the snapshot partial.
    """
    scene.world_state.location = "A dim server room, fans humming."
    scene.world_state.characters = {
        "Elena": CharacterState(
            snapshot="favors her left hand; a fresh burn on the wrist.",
            emotion="anxious",
        ),
    }
    scene.world_state.items = {
        "the silver dagger": ObjectState(
            snapshot="older than the hilt suggests; faint etching near the guard.",
        ),
    }
    scene.world_state.places = {
        "the north stairwell": PlaceState(
            snapshot="lit only by a flickering exit sign.",
        ),
    }
