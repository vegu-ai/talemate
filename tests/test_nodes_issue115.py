"""
Regression tests for the node code bugs surfaced by the docstring audit
(issue #115): runtime crashes, phantom/duplicate sockets, registry typo
renames (with legacy aliases) and declared-vs-effective property defaults.

Graph-level tests build small programmatic graphs (constant -> node under
test -> capture) and execute them, mirroring the pattern in
tests/test_nodes_run.py; pure error-path checks drive `run` directly via
the `run_node` helper.
"""

import pytest

import talemate.game.engine.nodes.load_definitions  # noqa: F401
import talemate.agents.director  # noqa: F401
from talemate.context import ActiveScene
from talemate.game.engine.nodes.core import (
    InputValueError,
    Node,
    StageExit,
)
from talemate.game.engine.nodes.registry import (
    NODE_ALIASES,
    NODES,
    get_node,
    import_talemate_node_definitions,
)
from talemate.game.engine.nodes.context_id import CompressContextIDPart, compress_name
from talemate.game.engine.nodes.logic import AsBool
from talemate.game.engine.nodes.number import AsNumber, Sum
from talemate.game.engine.nodes.prompt import GenerateResponse
from talemate.game.engine.nodes.raise_errors import Stop
from talemate.game.engine.nodes.scene_intent import SetScenePhase
from talemate.game.engine.nodes.state import CounterState, CounterStatePath
from talemate.game.engine.nodes.websocket import GetWebsocketRouter
from talemate.game.engine.nodes.history import ContextHistory
from talemate.game.engine.nodes.focal import Focal as FocalNode
from talemate.game.engine.nodes.assets import UpdateMessageAsset
from talemate.game.engine.nodes.world_state import GenerationOptions, Spices
from talemate.agents.editor.nodes import CleanUpNarration
from talemate.agents.director.auto_direct_nodes import GenerateSceneTypes
from talemate.agents.visual.nodes import ApplyStyle, ApplyStyles
from talemate.agents.visual.schema import VisualPrompt, VisualPromptPart
from talemate.world_state.templates.base import Template
from talemate.world_state.templates.visual import VisualStyle
from talemate.agents.world_state.nodes import StateReinforcement
from talemate.scene.schema import SceneType
from talemate.game import focal as focal_module
from talemate.world_state.manager import WorldStateManager
from talemate.world_state.templates.scene import SceneType as TemplateSceneType
from talemate import instance

from conftest import MockScene, bootstrap_scene
from _node_test_helpers import (
    build_graph,
    execute_graph,
    make_capture,
    make_constant,
    run_node,
)


# This runs once for the entire test session
@pytest.fixture(scope="session", autouse=True)
def load_node_definitions():
    import_talemate_node_definitions()


@pytest.fixture
def mock_scene():
    scene = MockScene()
    bootstrap_scene(scene)
    return scene


# ---------------------------------------------------------------------------
# Runtime crashes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clean_up_narration_graph(mock_scene):
    """CleanUpNarration called a non-existent editor method
    (cleanup_narration) and raised AttributeError whenever it ran."""
    captured = {}
    node = CleanUpNarration()
    node.set_property("force", True)
    const = make_constant(narration="She walked away. *A door slammed somewhere*")
    capture = make_capture(captured, "cleaned_narration")

    graph = build_graph(const, node, capture)
    graph.connect(
        const.get_output_socket("narration"), node.get_input_socket("narration")
    )
    graph.connect(
        node.get_output_socket("cleaned_narration"),
        capture.get_input_socket("cleaned_narration"),
    )

    await execute_graph(mock_scene, graph)

    assert isinstance(captured["cleaned_narration"], str)
    assert captured["cleaned_narration"]


@pytest.mark.asyncio
async def test_raise_stop_stage_exit(mock_scene):
    """raise/Stop offered "StageExit" as a choice but had no branch for it,
    raising `Unknown exception: StageExit` instead."""
    node = Stop()
    with pytest.raises(StageExit):
        await run_node(node, scene=mock_scene, inputs={"exception": "StageExit"})


@pytest.mark.asyncio
async def test_compress_context_id_part_graph(mock_scene):
    """CompressContextIDPart reused the `part` variable after hashing, so
    the `uncompressed` output emitted the compressed value."""
    captured = {}
    node = CompressContextIDPart()
    const = make_constant(part="Character Attributes")
    capture = make_capture(captured, "uncompressed", "compressed")

    graph = build_graph(const, node, capture)
    graph.connect(const.get_output_socket("part"), node.get_input_socket("part"))
    graph.connect(
        node.get_output_socket("uncompressed"), capture.get_input_socket("uncompressed")
    )
    graph.connect(
        node.get_output_socket("compressed"), capture.get_input_socket("compressed")
    )

    await execute_graph(mock_scene, graph)

    assert captured["uncompressed"] == "Character Attributes"
    assert captured["compressed"] == compress_name("Character Attributes")
    assert captured["uncompressed"] != captured["compressed"]


class _Unboolable:
    def __bool__(self):
        raise ValueError("boom")


@pytest.mark.asyncio
async def test_as_bool_error_path_raises_input_value_error(mock_scene):
    """AsBool's error path called InputValueError with a single argument,
    itself raising TypeError instead of the intended error."""
    node = AsBool()
    with pytest.raises(InputValueError):
        await run_node(node, scene=mock_scene, inputs={"value": _Unboolable()})


# ---------------------------------------------------------------------------
# Registry typo renames + legacy aliases
# ---------------------------------------------------------------------------


def test_clean_up_character_message_registry_rename():
    cls = NODES["agents/editor/CleanUpCharacterMessage"]
    assert cls._registry == "agents/editor/CleanUpCharacterMessage"
    assert "agents/editor/CleanUoCharacterMessage" not in NODES


def test_legacy_registry_aliases_resolve():
    """Saved graphs referencing the old typo'd registry names must keep
    loading - get_node resolves them through NODE_ALIASES."""
    assert (
        get_node("agents/editor/CleanUoCharacterMessage")
        is NODES["agents/editor/CleanUpCharacterMessage"]
    )
    assert (
        get_node("agernts/director/chat/instructGamestateUpdates")
        is NODES["agents/director/chat/instructGamestateUpdates"]
    )


def test_legacy_registry_name_migrates_on_serialization():
    """A node instantiated from a legacy registry reference serializes with
    the fixed registry string - re-saving a graph auto-migrates it.
    NodeBase.__init__ discards any incoming `registry` kwarg in favor of the
    class's `_registry`."""
    node = get_node("agents/editor/CleanUoCharacterMessage")(
        registry="agents/editor/CleanUoCharacterMessage"
    )
    assert node.registry == "agents/editor/CleanUpCharacterMessage"
    assert node.model_dump()["registry"] == "agents/editor/CleanUpCharacterMessage"


def test_scene_local_definition_under_legacy_name_keeps_priority(mock_scene):
    """A scene-local node definition registered under a legacy (typo'd)
    registry name must still win over the shipped node the alias points
    to - the alias only applies when the raw name resolves nowhere."""

    class _SceneLocalOverride(Node):
        pass

    mock_scene._NODE_DEFINITIONS = {
        "agents/editor/CleanUoCharacterMessage": _SceneLocalOverride
    }
    with ActiveScene(mock_scene):
        assert get_node("agents/editor/CleanUoCharacterMessage") is _SceneLocalOverride


def test_shipped_director_modules_use_fixed_registry_name():
    """The two shipped module JSONs were updated to the fixed registry
    path; the typo'd name must not be registered anymore."""
    assert "agents/director/chat/instructGamestateUpdates" in NODES
    assert "agernts/director/chat/instructGamestateUpdates" not in NODES
    for legacy, current in NODE_ALIASES.items():
        assert legacy not in NODES
        assert current in NODES


# ---------------------------------------------------------------------------
# Phantom / duplicate sockets
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "node_cls",
    [GenerateResponse, CounterState, CounterStatePath],
)
def test_no_duplicate_sockets(node_cls):
    """GenerateResponse added its `agent` output twice; CounterState added
    a second `value` output on top of the one from the base setup."""
    node = node_cls()
    output_names = [sock.name for sock in node.outputs]
    assert len(output_names) == len(set(output_names)), output_names
    input_names = [sock.name for sock in node.inputs]
    assert len(input_names) == len(set(input_names)), input_names


def test_get_websocket_router_has_no_state_socket():
    """GetWebsocketRouter set a `state` output value without any state
    socket existing (silently dropped)."""
    node = GetWebsocketRouter()
    assert [sock.name for sock in node.outputs] == [
        "router",
        "websocket_router",
        "websocket_handler",
    ]


def test_focal_template_input_socket_type():
    """Focal.setup passed socket_typoe= (silently swallowed), leaving the
    template input typed "any"."""
    node = FocalNode()
    assert node.get_input_socket("template").socket_type == "str"


@pytest.mark.asyncio
async def test_generate_scene_types_outputs_scene_types(mock_scene, monkeypatch):
    """GenerateSceneTypes set a `scene_types` output value without a socket;
    the socket now exists and receives the generated types."""
    captured = {}
    scene_types = [SceneType(id="t1", name="T1", description="", instructions="")]

    director = instance.get_agent("director")

    async def fake_generate(instructions, max_scene_types=1):
        return scene_types

    monkeypatch.setattr(director, "auto_direct_generate_scene_types", fake_generate)

    node = GenerateSceneTypes()
    node.set_property("instructions", "whatever")
    const = make_constant(state=True)
    capture = make_capture(captured, "state", "scene_types")

    graph = build_graph(const, node, capture)
    graph.connect(const.get_output_socket("state"), node.get_input_socket("state"))
    graph.connect(node.get_output_socket("state"), capture.get_input_socket("state"))
    graph.connect(
        node.get_output_socket("scene_types"), capture.get_input_socket("scene_types")
    )

    await execute_graph(mock_scene, graph)

    assert captured["scene_types"] == scene_types


@pytest.mark.asyncio
async def test_auto_direct_generate_scene_types_returns_scene_types(
    mock_scene, monkeypatch
):
    """auto_direct_generate_scene_types discarded the generated types; it
    now returns them as SceneType models from both callback paths, and the
    template path registers the type on the scene's intent state (its
    apply_to_scene guard checked a non-existent `scene_intent` attribute,
    so template-picked types were never stored anywhere)."""
    template = TemplateSceneType(name="Combat", description="fighting")

    class _FakeCollection:
        templates = {"combat": template}

        def find_by_name(self, name):
            return template if name == "Combat" else None

    async def fake_get_templates(self, types=None):
        return _FakeCollection()

    async def fake_request(self, template_name=None, prompt=None, retry_state=None):
        await self.callbacks["add_from_template"].fn(id="Combat")
        await self.callbacks["generate_scene_type"].fn(
            id="duel", name="Duel", description="a duel", instructions=None
        )
        return ""

    monkeypatch.setattr(WorldStateManager, "get_templates", fake_get_templates)
    monkeypatch.setattr(focal_module.Focal, "request", fake_request)

    director = instance.get_agent("director")
    with ActiveScene(mock_scene):
        generated = await director.auto_direct_generate_scene_types(
            instructions="", max_scene_types=2
        )

    assert [type(st) for st in generated] == [SceneType, SceneType]
    assert {st.id for st in generated} == {"combat", "duel"}
    assert type(mock_scene.intent_state.scene_types["combat"]) is SceneType
    assert type(mock_scene.intent_state.scene_types["duel"]) is SceneType


@pytest.mark.asyncio
async def test_apply_styles_state_passthrough(mock_scene):
    """ApplyStyles set a `state` output value without a socket; the state
    passthrough socket now exists (matching FinalizePrompt)."""
    captured = {}
    node = ApplyStyles()
    prompt = VisualPrompt()
    const = make_constant(state="marker", prompt=prompt)
    capture = make_capture(captured, "state", "prompt")

    graph = build_graph(const, node, capture)
    graph.connect(const.get_output_socket("state"), node.get_input_socket("state"))
    graph.connect(const.get_output_socket("prompt"), node.get_input_socket("prompt"))
    graph.connect(node.get_output_socket("state"), capture.get_input_socket("state"))
    graph.connect(node.get_output_socket("prompt"), capture.get_input_socket("prompt"))

    await execute_graph(mock_scene, graph)

    assert captured["state"] == "marker"
    assert isinstance(captured["prompt"], VisualPrompt)


class _FakeTemplateCollection:
    """Minimal stand-in for the world-state template Collection, keyed by
    (group_uid, template_uid)."""

    def __init__(self, templates: dict):
        self.templates = templates

    def find_template(self, group_uid, template_uid):
        return self.templates.get((group_uid, template_uid))

    def find_template_by_id(self, template_id):
        if not template_id:
            return None
        try:
            group_uid, template_uid = template_id.split("__", 1)
        except ValueError:
            return None
        return self.find_template(group_uid, template_uid)


def _digital_art_template() -> VisualStyle:
    return VisualStyle(
        name="Digital Art",
        uid="digital_art",
        group="visual_styles",
        positive_keywords=["masterpiece", "vibrant colors"],
        negative_keywords=["blurry"],
        positive_descriptive="digital painting",
        instructions="Make it pop",
    )


def _run_apply_style_graph(captured, template_id):
    node = ApplyStyle()
    prompt = VisualPrompt()
    const = make_constant(state="marker", prompt=prompt, template_id=template_id)
    capture = make_capture(captured, "state", "prompt", "template_id", "prompt_part")

    graph = build_graph(const, node, capture)
    graph.connect(const.get_output_socket("state"), node.get_input_socket("state"))
    graph.connect(const.get_output_socket("prompt"), node.get_input_socket("prompt"))
    graph.connect(
        const.get_output_socket("template_id"), node.get_input_socket("template_id")
    )
    graph.connect(node.get_output_socket("state"), capture.get_input_socket("state"))
    graph.connect(node.get_output_socket("prompt"), capture.get_input_socket("prompt"))
    graph.connect(
        node.get_output_socket("template_id"), capture.get_input_socket("template_id")
    )
    graph.connect(
        node.get_output_socket("prompt_part"), capture.get_input_socket("prompt_part")
    )
    return graph, prompt


@pytest.mark.asyncio
async def test_apply_style_state_passthrough(mock_scene):
    """ApplyStyle passes state, prompt and template_id through (issue #115
    socket regression coverage, now exercising a real template id after the
    #123 fix)."""
    mock_scene._world_state_templates = _FakeTemplateCollection(
        {("visual_styles", "digital_art"): _digital_art_template()}
    )
    captured = {}
    graph, prompt = _run_apply_style_graph(captured, "visual_styles__digital_art")

    await execute_graph(mock_scene, graph)

    assert captured["state"] == "marker"
    assert captured["prompt"] is prompt
    assert captured["template_id"] == "visual_styles__digital_art"


@pytest.mark.asyncio
async def test_apply_style_resolves_template_part(mock_scene):
    """apply_style crashed on any real template id (str fed into the
    VIS_TYPE-expecting style_template); it now resolves the template directly
    via find_template and inserts a part built from it at the front of the
    prompt's part list (issue #123)."""
    mock_scene._world_state_templates = _FakeTemplateCollection(
        {("visual_styles", "digital_art"): _digital_art_template()}
    )
    captured = {}
    graph, prompt = _run_apply_style_graph(captured, "visual_styles__digital_art")

    await execute_graph(mock_scene, graph)

    part = captured["prompt_part"]
    assert isinstance(part, VisualPromptPart)
    assert prompt.parts[0] is part
    assert part.positive_keywords_raw == ["masterpiece", "vibrant colors"]
    assert part.negative_keywords_raw == ["blurry"]
    assert part.positive_descriptive == "digital painting"
    assert part.instructions == "Make it pop"


@pytest.mark.asyncio
async def test_apply_style_wrong_template_type_no_crash(mock_scene):
    """A valid id pointing at a non-visual template (e.g. a writing style)
    must degrade to no part instead of crashing on the missing keyword
    fields (PR #132 review)."""
    mock_scene._world_state_templates = _FakeTemplateCollection(
        {("writing_styles", "flowery"): Template(name="Flowery")}
    )
    captured = {}
    graph, prompt = _run_apply_style_graph(captured, "writing_styles__flowery")

    await execute_graph(mock_scene, graph)

    assert captured["prompt_part"] is None
    assert prompt.parts == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "template_id",
    [
        "visual_styles__nonexistent",  # unknown template
        "nonexistent_group__digital_art",  # unknown group
        "UNSPECIFIED",  # not a template id (former special case, #123)
        "no-separator",  # malformed
        "",  # empty
    ],
)
async def test_apply_style_unknown_template_id_no_crash(mock_scene, template_id):
    """Unknown, malformed or empty template ids resolve to no part and leave
    the prompt unchanged instead of crashing (issue #123)."""
    mock_scene._world_state_templates = _FakeTemplateCollection(
        {("visual_styles", "digital_art"): _digital_art_template()}
    )
    captured = {}
    graph, prompt = _run_apply_style_graph(captured, template_id)

    await execute_graph(mock_scene, graph)

    assert captured["prompt_part"] is None
    assert prompt.parts == []
    assert captured["prompt"] is prompt


@pytest.mark.asyncio
async def test_state_reinforcement_outputs_reinforcement(mock_scene, monkeypatch):
    """StateReinforcement declared a `reinforcement` output socket that
    run() never set; it now emits the added/updated Reinforcement."""
    captured = {}

    world_state_agent = instance.get_agent("world_state")

    async def fake_update(question, character=None, reset=False):
        return "reinforcement message"

    monkeypatch.setattr(world_state_agent, "update_reinforcement", fake_update)

    node = StateReinforcement()
    const = make_constant(state=True, query_or_detail="Current mood")
    capture = make_capture(captured, "message", "reinforcement")

    graph = build_graph(const, node, capture)
    graph.connect(const.get_output_socket("state"), node.get_input_socket("state"))
    graph.connect(
        const.get_output_socket("query_or_detail"),
        node.get_input_socket("query_or_detail"),
    )
    graph.connect(
        node.get_output_socket("message"), capture.get_input_socket("message")
    )
    graph.connect(
        node.get_output_socket("reinforcement"),
        capture.get_input_socket("reinforcement"),
    )

    await execute_graph(mock_scene, graph)

    assert captured["message"] == "reinforcement message"
    assert captured["reinforcement"] is not None
    assert captured["reinforcement"].question == "Current mood"


@pytest.mark.asyncio
async def test_counter_state_graph(mock_scene):
    """CounterState still counts correctly with the duplicate `value`
    output removed."""
    captured = {}
    node = CounterState()
    node.set_property("name", "my_counter")
    const = make_constant(state=True)
    capture = make_capture(captured, "value", "new_cycle")

    graph = build_graph(const, node, capture)
    graph.connect(const.get_output_socket("state"), node.get_input_socket("state"))
    graph.connect(node.get_output_socket("value"), capture.get_input_socket("value"))
    graph.connect(
        node.get_output_socket("new_cycle"), capture.get_input_socket("new_cycle")
    )

    await execute_graph(mock_scene, graph)

    assert captured["value"] == 1
    assert captured["new_cycle"] is True


# ---------------------------------------------------------------------------
# Declared vs effective property defaults
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "node_cls, prop",
    [
        (ContextHistory, "keep_investigation_messages"),
        (ContextHistory, "keep_reinforcement_messages"),
        (SetScenePhase, "scene_type"),
        (AsNumber, "number_type"),
    ],
)
def test_fields_default_matches_setup_value(node_cls, prop):
    node = node_cls()
    assert node.get_property_field(prop).default == node.properties[prop]


# ---------------------------------------------------------------------------
# Misc property / socket metadata
# ---------------------------------------------------------------------------


def test_update_message_asset_has_no_asset_type_property():
    """UpdateMessageAsset declared an `asset_type` property that run()
    never used (update_message_asset takes no such argument)."""
    node = UpdateMessageAsset()
    assert "asset_type" not in node.field_definitions


def test_spices_socket_types_line_up():
    """GenerationOptions' spices input was typed "generation_options" and
    the Spices node's output "list" - both are now "spices" so they can
    actually be wired together in the editor."""
    gen_opts = GenerationOptions()
    spices = Spices()
    assert gen_opts.get_input_socket("spices").socket_type == "spices"
    assert spices.get_output_socket("spices").socket_type == "spices"
    assert "spices" not in gen_opts.properties


def test_sum_numbers_property_field():
    """Sum set a `numbers` property with no PropertyField (untyped in the
    editor UI)."""
    node = Sum()
    field = node.get_property_field("numbers")
    assert field.type == "list"
    assert field.default == []
