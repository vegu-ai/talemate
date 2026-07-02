"""
Baseline snapshot tests for shared/common prompt utilities that render
without going through an agent — currently the `render_game_state` Jinja
global and its underlying `gamestate-context-path.jinja2` template.

These tests render templates directly via `Prompt.get` / `Prompt.from_text`
and snapshot the output. Run with --update-baselines to create/update.
"""

from unittest.mock import Mock

import talemate.instance as instance
from talemate.context import active_scene
from talemate.prompts.base import Prompt
from talemate.util.path import get_path_value
from talemate.world_state import CharacterState, ObjectState, PlaceState

from ..helpers import create_scene_with_characters, register_world_state_toggle


AGENT = "common"


def _render_via_global(
    template_text: str,
    *,
    scene_variables: dict | None = None,
    vars: dict | None = None,
    client=None,
) -> str:
    """Render a template that calls `render_game_state(...)`.

    `scene_variables`, when provided, populates `active_scene.game_state.variables`
    for the duration of the render — that is the SoT the helper reads from.
    `vars` is forwarded to the prompt for any other template needs (only used
    by the precedence test that asserts vars are ignored).
    """
    prompt = Prompt.from_text(template_text, vars=vars or {})
    if client is not None:
        prompt.client = client

    if scene_variables is None:
        return prompt.render()

    scene = Mock()
    scene.game_state = Mock()
    scene.game_state.variables = scene_variables
    token = active_scene.set(scene)
    try:
        return prompt.render()
    finally:
        active_scene.reset(token)


def _client_with_format(data_format: str) -> Mock:
    """Minimal client mock that exposes only what the rendering layer reads."""
    client = Mock()
    client.data_format = data_format
    client.can_be_coerced = True
    client.reason_enabled = False
    return client


# ---------------------------------------------------------------------------
# End-to-end snapshots: {{ render_game_state(...) }} via Jinja global
# ---------------------------------------------------------------------------


class TestRenderGameStateGlobal:
    """Snapshot the full chain: outer template → render_game_state global
    → active_scene.game_state.variables → get_path_value → sub-Prompt render.

    `render_game_state` reads strictly from the SoT (active scene's game state)
    and ignores any `gamestate` value passed via prompt vars."""

    def test_resolves_nested_path(self, baseline_checker):
        out = _render_via_global(
            'BEFORE\n{{ render_game_state("player/status") }}\nAFTER',
            scene_variables={"player": {"status": {"hp": 12, "mana": 5}}},
        )
        baseline_checker(out, AGENT, "gamestate_path_global_resolves")

    def test_resolves_single_segment_path(self, baseline_checker):
        # Top-level key with no slashes — common shape for flat gamestates.
        out = _render_via_global(
            '{{ render_game_state("player_stats") }}',
            scene_variables={"player_stats": {"hp": 12, "mana": 5}},
        )
        baseline_checker(out, AGENT, "gamestate_path_global_single_segment")

    def test_missing_path_renders_empty(self, baseline_checker):
        out = _render_via_global(
            'BEFORE\n{{ render_game_state("nope/missing") }}\nAFTER',
            scene_variables={"player": {"hp": 12}},
        )
        baseline_checker(out, AGENT, "gamestate_path_global_missing")

    def test_no_active_scene_renders_empty(self, baseline_checker):
        # No scene set + no scene_variables → renders empty, no crash.
        out = _render_via_global(
            'BEFORE\n{{ render_game_state("player") }}\nAFTER',
        )
        baseline_checker(out, AGENT, "gamestate_path_global_no_gamestate_var")

    def test_custom_title(self, baseline_checker):
        out = _render_via_global(
            '{{ render_game_state("player/status", title="PLAYER") }}',
            scene_variables={"player": {"status": {"hp": 12}}},
        )
        baseline_checker(out, AGENT, "gamestate_path_global_custom_title")

    def test_leading_slash_tolerated(self, baseline_checker):
        out = _render_via_global(
            '{{ render_game_state("/player/status") }}',
            scene_variables={"player": {"status": {"hp": 12}}},
        )
        baseline_checker(out, AGENT, "gamestate_path_global_leading_slash")

    def test_intermediate_non_dict_renders_empty(self, baseline_checker):
        # 'world' is a scalar — can't traverse into it, so the path is
        # treated as unresolvable and the section is omitted.
        out = _render_via_global(
            'BEFORE\n{{ render_game_state("world/inner") }}\nAFTER',
            scene_variables={"world": "flat"},
        )
        baseline_checker(out, AGENT, "gamestate_path_global_intermediate_non_dict")

    def test_reads_from_active_scene(self, baseline_checker):
        # The canonical case: the user puts `{{ render_game_state("vegu_status") }}`
        # in a custom override (e.g. dialogue.jinja2) and the helper resolves
        # against scene.game_state.variables without any bridging boilerplate.
        out = _render_via_global(
            '{{ render_game_state("vegu_status") }}',
            scene_variables={
                "vegu_status": {"time": "17:00", "health": "normal"},
            },
        )
        baseline_checker(out, AGENT, "gamestate_path_global_active_scene_fallback")

    def test_vars_gamestate_is_ignored(self, baseline_checker):
        # Even if a caller passes a `gamestate` var, the SoT (active scene's
        # game state) still wins. This guarantees rendered output cannot
        # diverge from the live state.
        out = _render_via_global(
            '{{ render_game_state("vegu_status") }}',
            scene_variables={"vegu_status": {"from": "scene"}},
            vars={"gamestate": {"vegu_status": {"from": "vars"}}},
        )
        baseline_checker(out, AGENT, "gamestate_path_global_vars_ignored")

    def test_resolves_scalar_leaf(self, baseline_checker):
        # Path resolves to a non-container value — must still render.
        out = _render_via_global(
            '{{ render_game_state("player/state") }}',
            scene_variables={"player": {"state": "ready"}},
        )
        baseline_checker(out, AGENT, "gamestate_path_global_scalar")

    def test_resolves_list_leaf(self, baseline_checker):
        out = _render_via_global(
            '{{ render_game_state("inventory") }}',
            scene_variables={"inventory": ["sword", "potion", "key"]},
        )
        baseline_checker(out, AGENT, "gamestate_path_global_list")

    def test_budget_exceeded_renders_empty(self, baseline_checker):
        # Tiny budget against a large value — the section drops out entirely.
        big = {f"item_{i}": "x" * 50 for i in range(40)}
        out = _render_via_global(
            '{{ render_game_state("inventory", budget=10) }}',
            scene_variables={"inventory": big},
        )
        baseline_checker(out, AGENT, "gamestate_path_global_budget_exceeded")

    def test_budget_zero_means_unlimited(self, baseline_checker):
        # budget=0 is falsy in the template → cap is bypassed, value renders.
        out = _render_via_global(
            '{{ render_game_state("player/status", budget=0) }}',
            scene_variables={"player": {"status": {"hp": 12}}},
        )
        baseline_checker(out, AGENT, "gamestate_path_global_budget_zero")

    def test_note_renders_above_data_block(self, baseline_checker):
        # `note` reaches the sub-Prompt and lands between the Path: line and
        # the Data format: line, with blank-line separation on both sides.
        out = _render_via_global(
            '{{ render_game_state("player/status", note="Updated each turn from sensors.") }}',
            scene_variables={"player": {"status": {"hp": 12, "mana": 5}}},
        )
        baseline_checker(out, AGENT, "gamestate_path_global_with_note")

    def test_multiline_note_renders_verbatim(self, baseline_checker):
        out = _render_via_global(
            '{{ render_game_state("player/status", note=note) }}',
            scene_variables={"player": {"status": {"hp": 12}}},
            vars={"note": "Player status snapshot.\nUpdated each turn from sensors."},
        )
        baseline_checker(out, AGENT, "gamestate_path_global_with_multiline_note")

    def test_yaml_format_propagates_from_client(self, baseline_checker):
        # When the parent prompt has a client with data_format='yaml', the
        # sub-Prompt created by render_game_state must inherit it so the
        # block renders as YAML rather than the json default.
        out = _render_via_global(
            '{{ render_game_state("player/status") }}',
            scene_variables={"player": {"status": {"hp": 12, "mana": 5}}},
            client=_client_with_format("yaml"),
        )
        baseline_checker(out, AGENT, "gamestate_path_global_yaml_via_client")

    def test_json_format_propagates_from_client(self, baseline_checker):
        # Sanity counterpart: an explicit json client renders json (matching
        # the default) — locks in that the propagation path is exercised in
        # both directions, not just yaml.
        out = _render_via_global(
            '{{ render_game_state("player/status") }}',
            scene_variables={"player": {"status": {"hp": 12, "mana": 5}}},
            client=_client_with_format("json"),
        )
        baseline_checker(out, AGENT, "gamestate_path_global_json_via_client")


# ---------------------------------------------------------------------------
# Plain assertions for get_path_value (the helper backing render_game_state).
# Edge cases are easier to read as direct asserts than as snapshot files.
# ---------------------------------------------------------------------------


class TestGetPathValue:
    GS = {
        "player": {"status": {"hp": 10, "mana": 4}, "name": "Vegu"},
        "world": "flat",  # scalar mid-path
        "inventory": ["sword", "potion"],
    }

    def test_resolves_nested_dict(self):
        assert get_path_value(self.GS, "player/status") == {"hp": 10, "mana": 4}

    def test_resolves_leaf_scalar(self):
        assert get_path_value(self.GS, "player/status/hp") == 10

    def test_resolves_top_level_scalar(self):
        assert get_path_value(self.GS, "world") == "flat"

    def test_resolves_top_level_list(self):
        assert get_path_value(self.GS, "inventory") == ["sword", "potion"]

    def test_missing_segment_returns_default(self):
        assert get_path_value(self.GS, "player/missing") is None
        assert get_path_value(self.GS, "player/missing", default="-") == "-"

    def test_non_dict_intermediate_returns_default(self):
        # 'world' is a string; can't walk into it.
        assert get_path_value(self.GS, "world/inner") is None
        assert get_path_value(self.GS, "world/inner", default="-") == "-"

    def test_leading_and_trailing_slashes_tolerated(self):
        assert get_path_value(self.GS, "/player/name") == "Vegu"
        assert get_path_value(self.GS, "player/name/") == "Vegu"

    def test_none_container_returns_default(self):
        assert get_path_value(None, "player") is None
        assert get_path_value(None, "player", default="-") == "-"

    def test_empty_path_returns_default(self):
        assert get_path_value(self.GS, "") is None
        assert get_path_value(self.GS, "/") is None


# ---------------------------------------------------------------------------
# Snapshots: common/world-state-snapshot.jinja2 (durable snapshot → scene memory)
# ---------------------------------------------------------------------------


def _render_world_state_snapshot(seed, *, toggle: bool = True) -> str:
    """Render the world-state-snapshot partial against a seeded scene.

    A minimal world_state agent is registered so the in-template
    ``agent_config("world_state.update_world_state.inject_as_scene_memory")``
    gate resolves to ``toggle``. The scene and its actors are real; only the
    registry agent is a stand-in for the config lookup.
    """
    original_agents = instance.AGENTS.copy()
    register_world_state_toggle(toggle)

    scene = create_scene_with_characters()
    seed(scene.world_state)
    token = active_scene.set(scene)
    try:
        return Prompt.get("common.world-state-snapshot", vars={"scene": scene}).render()
    finally:
        active_scene.reset(token)
        instance.AGENTS.clear()
        instance.AGENTS.update(original_agents)


class TestWorldStateSnapshotBaselines:
    """Snapshot the rendered SCENE NOTES block fed into consumer prompts."""

    def test_full_snapshot(self, baseline_checker):
        def seed(ws):
            ws.location = "A dim server room, fans humming."
            ws.characters = {
                "Elena": CharacterState(
                    snapshot="favors her left hand; a fresh burn on the wrist.",
                    emotion="anxious",
                ),
                "Marcus": CharacterState(
                    snapshot="rolled sleeves, ink stains on the right cuff.",
                    emotion=None,
                ),
            }
            ws.items = {
                "the silver dagger": ObjectState(
                    snapshot="older than the hilt suggests; faint etching near the guard.",
                ),
            }
            ws.places = {
                "the north stairwell": PlaceState(
                    snapshot="lit only by a flickering exit sign.",
                ),
            }

        out = _render_world_state_snapshot(seed)
        baseline_checker(out, AGENT, "world_state_snapshot_full")

    def test_location_only(self, baseline_checker):
        def seed(ws):
            ws.location = "A rain-slick alley behind the market."

        out = _render_world_state_snapshot(seed)
        baseline_checker(out, AGENT, "world_state_snapshot_location_only")

    def test_disabled_renders_empty(self, baseline_checker):
        def seed(ws):
            ws.location = "A dim server room, fans humming."
            ws.characters = {"Elena": CharacterState(snapshot="favors her left hand.")}

        out = _render_world_state_snapshot(seed, toggle=False)
        baseline_checker(out, AGENT, "world_state_snapshot_disabled")
