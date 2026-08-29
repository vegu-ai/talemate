"""
Unit tests for `talemate.world_state.templates.scene`.

Covers:
- `SceneType.to_scene_type_dict()` ID derivation from name
- `apply_to_scene` happy path: registers on scene.intent_state.scene_types
- `apply_to_scene` no-intent-state path: returns the scene type but does not crash
- field defaults
"""

from _world_state_helpers import scene  # noqa: F401 - pytest fixture
from talemate.scene.schema import SceneType as IntentSceneType
from talemate.world_state.templates.scene import SceneType


# ---------------------------------------------------------------------------
# to_scene_type_dict
# ---------------------------------------------------------------------------


class TestSceneTypeToDict:
    def test_id_derived_from_name(self):
        st = SceneType(name="Battle Scene", description="Fight!")
        d = st.to_scene_type_dict()
        assert d["id"] == "battle_scene"
        assert d["name"] == "Battle Scene"
        assert d["description"] == "Fight!"
        assert d["instructions"] is None

    def test_id_handles_multiple_spaces_and_case(self):
        st = SceneType(name="Foo BAR baz", description="d")
        assert st.to_scene_type_dict()["id"] == "foo_bar_baz"

    def test_includes_instructions_when_set(self):
        st = SceneType(
            name="Solo",
            description="d",
            instructions="Make it intense.",
        )
        d = st.to_scene_type_dict()
        assert d["instructions"] == "Make it intense."

    def test_template_type_default(self):
        st = SceneType(name="X", description="y")
        assert st.template_type == "scene_type"


# ---------------------------------------------------------------------------
# apply_to_scene
# ---------------------------------------------------------------------------


class TestApplyToScene:
    def test_apply_registers_on_intent_state(self, scene):
        st = SceneType(name="Battle Scene", description="Fight!")
        result = st.apply_to_scene(scene)

        assert type(result) is IntentSceneType
        assert result.id == "battle_scene"
        assert "battle_scene" in scene.intent_state.scene_types
        stored = scene.intent_state.scene_types["battle_scene"]
        assert type(stored) is IntentSceneType
        assert stored.name == "Battle Scene"

    def test_apply_with_none_scene(self):
        st = SceneType(name="None Scene", description="d")
        result = st.apply_to_scene(None)
        assert result.id == "none_scene"

    def test_apply_with_falsy_intent_state_skips_storage(self, scene):
        scene.intent_state = None
        st = SceneType(name="X", description="y")
        result = st.apply_to_scene(scene)
        # We still get the scene type back, intent_state is not mutated.
        assert result.id == "x"
        assert scene.intent_state is None
