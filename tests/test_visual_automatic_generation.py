import asyncio
from typing import ClassVar

import pydantic
import pytest

import talemate.agents.visual.generation as generation_module
import talemate.emit.async_signals as async_signals
from talemate.agents.director.chat.nodes import GetDirectorChatContext
from talemate.agents.director.scene_direction.mixin import scene_direction_context
from talemate.agents.visual.agent import VisualAgent
from talemate.agents.visual.backends import Backend
from talemate.agents.visual.nodes import (
    GenerationRequestNode,
    UnpackGenerationRequest,
    UnpackGenerationResponse,
)
from talemate.agents.visual.schema import (
    PROMPT_TYPE,
    VIS_TYPE,
    BackendStatus,
    BackendStatusType,
    GenerationRequest,
    GenerationResponse,
    VisualPrompt,
)
from talemate.context import active_scene

from _node_test_helpers import run_node

PURPOSE = "world_state.scene_background"
SOURCE = "world_state.backgrounds"


class RecordingBackend:
    name = "recording"

    def __init__(self):
        self.requests = []

    async def generate(self, request, response):
        self.requests.append(request)
        return response

    async def cancel_request(self):
        pass


class ModuleBackend(Backend):
    name: ClassVar[str] = "module-test"
    label: ClassVar[str] = "Module test"
    image_create: ClassVar[bool] = True
    image_edit: ClassVar[bool] = False
    image_analyzation: ClassVar[bool] = False
    description: ClassVar[str] = "Records the requests it receives"
    prompt_type: PROMPT_TYPE = PROMPT_TYPE.DESCRIPTIVE
    status: BackendStatus = BackendStatus(type=BackendStatusType.OK)
    requests: list = pydantic.Field(default_factory=list)

    async def generate(self, request, response):
        self.requests.append(request)
        return response

    async def cancel_request(self):
        pass


@pytest.fixture
def agent(monkeypatch):
    monkeypatch.setattr(generation_module, "emit", lambda *args, **kwargs: None)
    monkeypatch.setattr(VisualAgent, "can_generate_images", property(lambda s: True))
    monkeypatch.setattr(VisualAgent, "backend", None, raising=False)
    agent = VisualAgent()
    agent.backend = RecordingBackend()

    async def no_finalize(request):
        pass

    async def no_status(*args, **kwargs):
        pass

    monkeypatch.setattr(agent, "finalize_prompt_request", no_finalize)
    monkeypatch.setattr(agent, "emit_status", no_status)
    return agent


def set_automatic_generation(agent, value: bool):
    agent.actions["_config"].config["automatic_generation"].value = value


@pytest.fixture
def active(scene):
    token = active_scene.set(scene)
    yield scene
    active_scene.reset(token)


@pytest.fixture
def refusals():
    received = []

    async def on_refused(emission):
        received.append(emission)

    async_signals.get("agent.visual.generation.refused").connect(on_refused)
    yield received
    async_signals.get("agent.visual.generation.refused").disconnect(on_refused)


async def settle():
    for _ in range(5):
        await asyncio.sleep(0)


def automatic_request() -> GenerationRequest:
    return GenerationRequest(
        purpose=PURPOSE,
        automatic_source=SOURCE,
        vis_type=VIS_TYPE.SCENE_BACKGROUND,
        character_name="Mara",
    )


async def test_an_automatic_generation_is_refused_while_the_setting_is_off(
    agent, active, refusals
):
    set_automatic_generation(agent, False)
    request = automatic_request()

    response = await agent.generate(request)
    await settle()

    assert response.refused
    assert response.id == request.id
    assert agent.backend.requests == []
    assert agent.generations_running(PURPOSE) == 0
    (refusal,) = refusals
    assert refusal.request is request
    assert (
        refusal.request.automatic_source,
        refusal.request.purpose,
        refusal.request.vis_type,
        refusal.request.character_name,
    ) == (SOURCE, PURPOSE, VIS_TYPE.SCENE_BACKGROUND, "Mara")
    assert "Automatic Generation" in refusal.reason


async def test_an_automatic_generation_runs_while_the_setting_is_on(
    agent, active, refusals
):
    set_automatic_generation(agent, True)

    response = await agent.generate(automatic_request())
    await settle()

    assert not response.refused
    assert [r.automatic_source for r in agent.backend.requests] == [SOURCE]
    assert refusals == []


@pytest.mark.parametrize("source", [None, ""])
async def test_a_requested_generation_ignores_the_setting(
    agent, active, refusals, source
):
    set_automatic_generation(agent, False)

    response = await agent.generate(GenerationRequest(automatic_source=source))
    await settle()

    assert not response.refused
    assert len(agent.backend.requests) == 1
    assert refusals == []


@pytest.mark.parametrize("source, expected", [(SOURCE, SOURCE), ("", None)])
async def test_generation_request_node_carries_the_automatic_source(source, expected):
    outputs = await run_node(
        GenerationRequestNode(),
        inputs={"prompt": VisualPrompt(), "automatic_source": source},
    )

    request = outputs["generation_request"]
    assert request.automatic_source == expected
    assert request.automatic == bool(expected)


async def test_unpack_nodes_expose_the_automatic_source_and_the_refusal():
    request = GenerationRequest(automatic_source=SOURCE)

    outputs = await run_node(
        UnpackGenerationRequest(), inputs={"generation_request": request}
    )
    assert outputs["automatic_source"] == SOURCE

    outputs = await run_node(
        UnpackGenerationRequest(),
        inputs={"generation_request": GenerationRequest()},
    )
    assert outputs["automatic_source"] == ""

    outputs = await run_node(
        UnpackGenerationResponse(),
        inputs={
            "generation_response": GenerationResponse(
                request=request, id=request.id, refused=True
            )
        },
    )
    assert outputs["refused"] is True


async def test_director_chat_context_reports_the_action_mode():
    outputs = await run_node(GetDirectorChatContext(), inputs={"state": True})
    assert outputs["mode"] == "chat"

    token = scene_direction_context.set({"in_direction_turn": True})
    try:
        outputs = await run_node(GetDirectorChatContext(), inputs={"state": True})
    finally:
        scene_direction_context.reset(token)
    assert outputs["mode"] == "scene_direction"


@pytest.mark.parametrize(
    "in_direction_turn, automatic_generation, offered",
    [
        (False, False, True),
        (True, True, True),
        (True, False, False),
    ],
)
async def test_create_image_is_offered_in_scene_direction_only_when_allowed(
    scene, monkeypatch, in_direction_turn, automatic_generation, offered
):
    from talemate.agents.director.action_core import gating
    from talemate.agents.director.action_core.gating import (
        extract_callback_descriptors,
    )
    from talemate.game.engine.nodes.tools.analysis import ensure_registry_loaded
    from talemate.instance import get_agent

    ensure_registry_loaded()
    monkeypatch.setattr(VisualAgent, "can_generate_images", property(lambda s: True))
    visual = get_agent("visual")
    monkeypatch.setattr(
        visual.actions["_config"].config["automatic_generation"],
        "value",
        automatic_generation,
    )

    # a condition that raises is logged and treated as offered
    errors = []
    monkeypatch.setattr(gating.log, "error", lambda *a, **kw: errors.append((a, kw)))

    token = scene_direction_context.set({"in_direction_turn": in_direction_turn})
    token_scene = active_scene.set(scene)
    try:
        descriptors = await extract_callback_descriptors("create_image")
    finally:
        active_scene.reset(token_scene)
        scene_direction_context.reset(token)

    action_ids = [d.action_id for d in descriptors]
    assert errors == []
    assert ("visuals.create_image" in action_ids) is offered


@pytest.mark.parametrize("automatic_generation", [True, False])
async def test_a_persisted_character_gets_a_visual_only_when_allowed(
    scene, monkeypatch, automatic_generation
):
    from talemate.agents.director.character_management import (
        PersistCharacterEmission,
    )
    from talemate.character import Character
    from talemate.game.engine.nodes.core import GraphContext
    from talemate.game.engine.nodes.layout import load_graph_from_file
    from talemate.game.engine.nodes.tools.analysis import ensure_registry_loaded
    from talemate.instance import get_agent
    from talemate.prompts import Prompt

    ensure_registry_loaded()
    monkeypatch.setattr(generation_module, "emit", lambda *args, **kwargs: None)
    monkeypatch.setattr(VisualAgent, "can_generate_images", property(lambda s: True))
    visual = get_agent("visual")
    monkeypatch.setattr(visual, "backend", ModuleBackend(), raising=False)

    async def no_finalize(request):
        pass

    async def send(prompt, *args, **kwargs):
        return "<KEYWORDS>mara, portrait</KEYWORDS><DESCRIPTIVE>Mara</DESCRIPTIVE>"

    async def no_status(*args, **kwargs):
        pass

    monkeypatch.setattr(visual, "finalize_prompt_request", no_finalize)
    monkeypatch.setattr(visual, "emit_status", no_status)
    monkeypatch.setattr(Prompt, "send", send)
    monkeypatch.setattr(
        visual.actions["_config"].config["automatic_generation"],
        "value",
        automatic_generation,
    )
    character = Character(name="Mara")
    scene.character_data["Mara"] = character

    module, _ = load_graph_from_file(
        "src/talemate/agents/director/modules/on-persist-character-generate-visual.json"
    )
    token = active_scene.set(scene)
    try:
        with GraphContext():
            await module.execute_from_event(
                PersistCharacterEmission(
                    agent=get_agent("director"), character=character
                )
            )
        await settle()
    finally:
        active_scene.reset(token)

    expected = ["director.persist_character"] if automatic_generation else []
    assert [r.automatic_source for r in visual.backend.requests] == expected


@pytest.mark.parametrize("handler_name", ["handle_generate", "handle_regenerate"])
async def test_a_replayed_request_from_the_frontend_is_the_users(
    agent, active, refusals, monkeypatch, handler_name
):
    import talemate.agents.visual.websocket_handler as handler_module

    set_automatic_generation(agent, False)
    monkeypatch.setattr(handler_module, "get_agent", lambda name: agent)
    stored = automatic_request().model_dump(mode="json")

    handler = handler_module.VisualWebsocketHandler(websocket_handler=None)
    await getattr(handler, handler_name)({"generation_request": stored})
    await settle()

    assert [r.automatic_source for r in agent.backend.requests] == [None]
    assert refusals == []


async def test_generate_visual_asset_passes_its_inputs_through(scene, monkeypatch):
    from talemate.game.engine.nodes.layout import load_graph_from_file
    from talemate.game.engine.nodes.tools.analysis import ensure_registry_loaded
    from talemate.prompts import Prompt

    from _node_test_helpers import (
        build_graph,
        execute_graph,
        make_capture,
        make_constant,
    )

    ensure_registry_loaded()

    async def send(prompt, *args, **kwargs):
        return "<KEYWORDS>harbour</KEYWORDS><DESCRIPTIVE>A harbour</DESCRIPTIVE>"

    monkeypatch.setattr(Prompt, "send", send)
    module, _ = load_graph_from_file(
        "src/talemate/agents/visual/modules/generate-visual-asset.json"
    )
    values = {
        "purpose": PURPOSE,
        "references": ["harbour-day"],
        "automatic_source": SOURCE,
    }
    source = make_constant(
        state=True,
        vis_type="SCENE_BACKGROUND",
        instructions="A harbour",
        prompt_only=True,
        **values,
    )
    captured = {}
    output = make_capture(captured, *values)
    graph = build_graph(source, module, output)
    for name in ("state", "vis_type", "instructions", "prompt_only", *values):
        graph.connect(source.get_output_socket(name), module.get_input_socket(name))
    for name in values:
        graph.connect(module.get_output_socket(name), output.get_input_socket(name))
    await execute_graph(scene, graph)

    assert captured == values


async def test_a_direction_turn_does_not_leak_its_mode_to_other_tasks(
    director, monkeypatch
):
    from talemate.agents.director.chat.nodes import detect_action_mode

    in_turn = asyncio.Event()
    release = asyncio.Event()
    seen = {}

    async def direction_generate(**kwargs):
        seen["inside"] = detect_action_mode()
        in_turn.set()
        await release.wait()
        return [], False

    monkeypatch.setattr(director, "_direction_generate", direction_generate)

    async def chat_task():
        await in_turn.wait()
        seen["other_task"] = detect_action_mode()
        release.set()

    other = asyncio.create_task(chat_task())
    await director.direction_execute_turn(always_on=True)
    await other

    assert seen == {"inside": "scene_direction", "other_task": "chat"}
    assert detect_action_mode() == "chat"


@pytest.fixture
def module_visual(monkeypatch):
    """The live visual agent with a recording backend and a canned prompt model."""
    from talemate.instance import get_agent
    from talemate.prompts import Prompt

    monkeypatch.setattr(generation_module, "emit", lambda *args, **kwargs: None)
    monkeypatch.setattr(VisualAgent, "can_generate_images", property(lambda s: True))
    visual = get_agent("visual")
    monkeypatch.setattr(visual, "backend", ModuleBackend(), raising=False)

    async def no_op(*args, **kwargs):
        pass

    async def send(prompt, *args, **kwargs):
        return "<KEYWORDS>portrait</KEYWORDS><DESCRIPTIVE>A portrait</DESCRIPTIVE>"

    monkeypatch.setattr(visual, "finalize_prompt_request", no_op)
    monkeypatch.setattr(visual, "emit_status", no_op)
    monkeypatch.setattr(Prompt, "send", send)
    return visual


@pytest.mark.parametrize(
    "automatic_generation, source, expected",
    [
        (True, "simulation_suite.add_character", ["simulation_suite.add_character"]),
        (False, "simulation_suite.add_character", []),
        (False, "", [None]),
    ],
)
async def test_generate_character_portrait_passes_the_automatic_source(
    scene, module_visual, monkeypatch, automatic_generation, source, expected
):
    from talemate.character import Character
    from talemate.game.engine.nodes.layout import load_graph_from_file
    from talemate.game.engine.nodes.tools.analysis import ensure_registry_loaded

    from _node_test_helpers import build_graph, execute_graph, make_constant

    ensure_registry_loaded()
    set_automatic_generation(module_visual, automatic_generation)
    character = Character(name="Imani")
    scene.character_data["Imani"] = character
    module, _ = load_graph_from_file(
        "src/talemate/agents/visual/modules/generate-character-portrait-legacy.json"
    )
    constant = make_constant(state=True, character=character, automatic_source=source)
    graph = build_graph(constant, module)
    for name in ("state", "character", "automatic_source"):
        graph.connect(constant.get_output_socket(name), module.get_input_socket(name))
    await execute_graph(scene, graph)
    await settle()

    assert [r.automatic_source for r in module_visual.backend.requests] == expected


@pytest.mark.parametrize("automatic_generation", [True, False])
async def test_simulation_suite_add_character_portrait_is_automatic(
    scene, module_visual, monkeypatch, automatic_generation
):
    import json

    from talemate.character import Character
    from talemate.game.engine.nodes.core import GraphContext, Node
    from talemate.game.engine.nodes.registry import NODES
    from talemate.game.engine.nodes.run import Function, FunctionWrapper
    from talemate.game.engine.nodes.tools.analysis import ensure_registry_loaded

    ensure_registry_loaded()
    set_automatic_generation(module_visual, automatic_generation)

    # the steps before the portrait call models; stand-ins keep their sockets
    class StubCreateCharacter(Node):
        def setup(self):
            for name in (
                "state",
                "character_name",
                "instructions",
                "generate",
                "generate_attributes",
                "is_active",
                "assign_voice",
                "generate_dialogue_instructions",
                "generate_example_dialogue",
            ):
                self.add_input(name, optional=True)
            self.add_output("state")
            self.add_output("character")

        async def run(self, state):
            name = self.get_input_value("character_name")
            character = Character(name=name)
            scene.character_data[name] = character
            self.set_output_values(
                {"state": self.get_input_value("state"), "character": character}
            )

    class StubStateReinforcement(Node):
        def setup(self):
            for name in ("state", "character", "instructions"):
                self.add_input(name, optional=True)
            self.add_output("state")

        async def run(self, state):
            self.set_output_values({"state": self.get_input_value("state")})

    monkeypatch.setitem(NODES, "agents/creator/CreateCharacter", StubCreateCharacter)
    monkeypatch.setitem(
        NODES, "agents/world_state/StateReinforcement", StubStateReinforcement
    )
    add_character = Function(
        **json.loads(
            open(
                "scenes/simulation-suite-v2/nodes/fn-sim-suite-add-character.json"
            ).read()
        )
    )

    token = active_scene.set(scene)
    try:
        with GraphContext() as state:
            await FunctionWrapper(add_character, add_character, state)(
                character_name="Dr. Imani Okafor", instructions="A ship's doctor"
            )
        await settle()
    finally:
        active_scene.reset(token)

    assert "Dr. Imani Okafor" in scene.character_data
    expected = ["simulation_suite.add_character"] if automatic_generation else []
    assert [r.automatic_source for r in module_visual.backend.requests] == expected
