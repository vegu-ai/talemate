import json
import zipfile
from pathlib import Path

import chromadb
import pytest
from chromadb.api.types import EmbeddingFunction

import talemate.instance as instance
from talemate.agents.memory import ChromaDBMemoryAgent
from talemate.character import Character, activate_character
from talemate.context import ActiveScene
from talemate.load import load_scene, load_scene_from_data
from talemate.prompts import Prompt
from talemate.shared_context import SharedContext
from talemate.world_state import ContextPin


class PinTestEmbedding(EmbeddingFunction):
    def __init__(self):
        pass

    def __call__(self, input):
        return [[1.0, 0.0] for _ in input]

    @staticmethod
    def name():
        return "pin-load-test"

    def get_config(self):
        return {}

    @staticmethod
    def build_from_config(config):
        return PinTestEmbedding()


@pytest.fixture
async def pin_load_scene(persistence_scene_factory, tmp_path, monkeypatch):
    scene = persistence_scene_factory()
    memory = ChromaDBMemoryAgent()
    memory.client = scene.mock_client
    memory.connect(scene)
    monkeypatch.setitem(instance.AGENTS, "memory", memory)
    with chromadb.PersistentClient(path=str(tmp_path / "memory")) as client:
        memory.db_client = client
        monkeypatch.setattr(
            memory,
            "_build_collection",
            lambda name: client.get_or_create_collection(
                name, embedding_function=PinTestEmbedding()
            ),
        )
        yield scene, memory


@pytest.fixture
def pin_scene_data():
    path = Path(__file__).parent / "data" / "load_pins" / "scene.json"
    return json.loads(path.read_text())


@pytest.mark.parametrize("mode", ["legacy", "perception"])
@pytest.mark.parametrize("loader", ["data", "json", "zip"])
@pytest.mark.parametrize("populated", [False, True])
@pytest.mark.parametrize("shared", [False, True])
async def test_load_preserves_valid_pins_and_removes_absent_sources(
    pin_load_scene, pin_scene_data, tmp_path, mode, loader, populated, shared
):
    scene, memory = pin_load_scene
    data = pin_scene_data
    data["knowledge_eligibility"] = mode
    data["game_state"] = {"variables": {"weather": "sunny"}}
    if shared and loader != "zip":
        character = Character(**data["character_data"].pop("Bob"), shared=True)
        await character.set_shared(True)
        scene.project_name = data["project_name"]
        path = Path(scene.shared_context_dir) / "pins.json"
        path.parent.mkdir(parents=True)
        context = SharedContext(
            filepath=path, character_data={"Bob": character}, format_version=1
        )
        await context.write_to_file()
        data["shared_context"] = path.name
    elif shared:
        data["character_data"]["Bob"]["shared"] = True
    scene.memory_id = data["memory_id"]
    scene.memory_session_id = data["memory_session_id"]
    with ActiveScene(scene):
        collection = memory._build_collection(memory.make_collection_name(scene))
        assert collection.count() == 0
        if populated:
            identities = list(data["world_state"]["pins"])
            collection.upsert(
                ids=identities,
                documents=["Cached text"] * len(identities),
            )
            assert collection.count() == len(identities)

        if loader == "data":
            await load_scene_from_data(scene, data, name="pins.json")
        elif loader == "json":
            path = tmp_path / "pins.json"
            path.write_text(json.dumps(data))
            await load_scene(scene, str(path), add_to_recent=False)
        else:
            path = tmp_path / "pins.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("scene.json", json.dumps(data))
            await load_scene(scene, str(path), add_to_recent=False)

        expected = {
            "archive",
            "Mira.description",
            "Mira.occupation",
            "Mira.detail.key",
            "world",
            "Bob.detail.secret",
        }
        assert set(scene.world_state.pins) == expected
        assert scene.world_state.pins["Mira.description"].active is False
        assert "Bob" in scene.inactive_characters
        assert scene.character_data["Bob"].shared is shared
        original_pin = ContextPin(**data["world_state"]["pins"]["Bob.detail.secret"])
        assert scene.world_state.pins["Bob.detail.secret"] == original_pin
        if loader != "data":
            documents = await memory.get_document(list(expected))
            assert set(documents) == expected - {"Bob.detail.secret"}
            assert all(document.raw for document in documents.values())
        if loader == "zip":
            saved = json.loads(Path(scene.full_path).read_text())
            assert set(saved["world_state"]["pins"]) == expected
            assert (
                ContextPin(**saved["world_state"]["pins"]["Bob.detail.secret"])
                == original_pin
            )
        if loader != "data":
            pins = await scene.world_state_manager.get_pins()
            assert pins.pins["Bob.detail.secret"].text == ""
            candidates = await scene.world_state_manager.get_pins(active=True)
            assert "Bob.detail.secret" in candidates.pins
            await scene.load_active_pins()
            assert {pin.pin.entry_id for pin in scene.active_pins} == expected - {
                "Bob.detail.secret",
                "Mira.description",
            }
            for template in ["common.extra-context-static", "visual.extra-context"]:
                rendered = Prompt.get(template, vars={"scene": scene}).render()
                assert "Bob - detail - secret" not in rendered
            await activate_character(scene, "Bob")
            pins = await scene.world_state_manager.get_pins()
            assert (
                "Bob hides a spare harbor key." in pins.pins["Bob.detail.secret"].text
            )
            assert scene.world_state.pins["Bob.detail.secret"] == original_pin
            await scene.load_active_pins()
            assert {pin.pin.entry_id for pin in scene.active_pins} == expected - {
                "Mira.description"
            }
            assert all(pin.text for pin in scene.active_pins)
            for template in ["common.extra-context-static", "visual.extra-context"]:
                rendered = Prompt.get(template, vars={"scene": scene}).render()
                assert "Bob hides a spare harbor key." in rendered


async def test_reset_prunes_pins_after_discarding_archive_sources(
    pin_load_scene, pin_scene_data
):
    scene, _ = pin_load_scene
    scene.archived_history = pin_scene_data["archived_history"]
    scene.world_state.pins["archive"] = ContextPin(
        **pin_scene_data["world_state"]["pins"]["archive"]
    )
    with ActiveScene(scene):
        await load_scene_from_data(scene, pin_scene_data, reset=True)
    assert scene.archived_history == []
    assert scene.world_state.pins == {}
