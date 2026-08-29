"""Unit tests for talemate.agents.director.nodes (PersistCharacter)."""

from __future__ import annotations

import pytest

from conftest import MockScene, bootstrap_scene
from _node_test_helpers import run_node

from talemate.agents.director.character_management import PersistCharacterRequest
from talemate.agents.director.nodes import PersistCharacter
from talemate.character import Character
from talemate.game.engine.nodes.registry import import_talemate_node_definitions
from talemate.instance import get_agent


@pytest.fixture(scope="session", autouse=True)
def _import_node_definitions():
    import_talemate_node_definitions()


@pytest.fixture
def scene():
    s = MockScene()
    bootstrap_scene(s)
    return s


@pytest.fixture
def director(scene):
    return get_agent("director")


class TestPersistCharacterNode:
    @pytest.mark.asyncio
    async def test_unconnected_character_name_becomes_empty_string(
        self, scene, director, monkeypatch
    ):
        """Regression: the optional character_name socket resolves to None
        when unconnected - the request must be built with "" so the
        determine_name path can run (the request model rejects None)."""
        captured = {}

        async def _persist(request):
            captured["request"] = request
            return Character(name="Determined Name")

        monkeypatch.setattr(director, "persist_character", _persist)

        node = PersistCharacter()
        outputs = await run_node(node, scene=scene)

        request = captured["request"]
        assert isinstance(request, PersistCharacterRequest)
        assert request.name == ""
        assert request.determine_name is True
        assert outputs["character"].name == "Determined Name"
