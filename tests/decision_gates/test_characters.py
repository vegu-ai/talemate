from unittest.mock import AsyncMock

import pytest

from talemate.agents.memory.schema import MemoryDocument
from talemate.character import Character
from talemate.exceptions import GenerationCancelled
from talemate.tale_mate import Actor


@pytest.fixture
def cast(gate_case):
    c = gate_case
    for name, description in [
        ("Mara", "Mara is the innkeeper. Her friends call her Red."),
        ("Will", "Will is a sailor."),
        ("Player", "A visitor."),
    ]:
        c.scene.character_data[name] = Character(name=name, description=description)
    c.scene.actors.append(Actor(character=c.scene.character_data["Player"], agent=None))
    c.scene.active_characters = ["Player"]
    c.scene.world_state.character_name_mappings = {"Mara": ["Red"]}
    return c


@pytest.mark.parametrize("consumer", ["memory", "snapshot"])
@pytest.mark.parametrize(
    "text",
    ["The innkeeper waves.", "She smiles; I will go.", "Red laughs.", "mara laughs."],
)
async def test_semantic_references_and_no_will_false_positive(
    cast, monkeypatch, consumer, text
):
    c = cast
    c.provider.answers = {
        name: {"type": "noul", "p_true": p}
        for name, p in [("Mara", 0.99), ("Will", 0.01)]
    }
    names, fetch = await reference_names(c, monkeypatch, consumer, text)
    assert names == ["Mara"]
    (request,) = c.provider.calls
    assert set(request.questions) == {"Mara", "Will"}
    assert request.state == text
    assert "innkeeper" in request.questions["Mara"].instructions
    assert "Red" in request.questions["Mara"].instructions
    if consumer == "memory":
        fetch.assert_awaited_once_with(
            {"character": "Mara", "typ": "base_attribute", "attr": "description"},
            viewer="Player",
        )
    record = next(iter(c.service.log.records.values()))
    assert record.template_uid == (
        "memory.decision-entity-references"
        if consumer == "memory"
        else "world_state.decision-snapshot-references"
    )
    assert record.actions[0].result["fallback_ran"] is False


@pytest.mark.parametrize("consumer", ["memory", "snapshot"])
async def test_no_result_after_the_scene_changed(cast, monkeypatch, consumer):
    c = cast
    respond = c.provider.respond

    def change_scene(request):
        monkeypatch.setattr(c.agent, "scene", object())
        return respond(request)

    monkeypatch.setattr(c.provider, "respond", change_scene)
    with pytest.raises(GenerationCancelled):
        await reference_names(c, monkeypatch, consumer, "Red laughs.")


async def reference_names(c, monkeypatch, consumer, text):
    if consumer == "snapshot":
        context = await c.agent.audience_context_with_references(c.scene, 1000, text)
        assert "Player" in [item["name"] for item in context["cast"]]
        assert all(item["established_knowledge"] == [] for item in context["cast"])
        return [
            item["name"] for item in context["cast"] if item["name"] != "Player"
        ], None

    async def documents(meta, **kwargs):
        name = meta["character"]
        return {
            f"{name}.description": MemoryDocument(
                name, meta=meta, id=f"{name}.description", raw=name
            )
        }

    fetch = AsyncMock(side_effect=documents)
    monkeypatch.setattr(c.memory, "get_documents_by_meta", fetch)
    docs = await c.agent.entity_lookup([text], viewer="Player")
    return [str(doc) for doc in docs], fetch


@pytest.mark.parametrize(
    "consumer,expected", [("memory", ["Mara"]), ("snapshot", ["Mara", "Will"])]
)
@pytest.mark.parametrize("mode", ["uncertain", "failed", "off", "disabled"])
async def test_reference_fallback_preserves_each_original_matcher(
    cast, monkeypatch, consumer, expected, mode
):
    c = cast
    if mode == "failed":
        c.provider.error = RuntimeError("request failed")
    elif mode == "off":
        c.memory.actions["retrieval"].config["entity_decision_model"].value = False
        c.agent.actions["update_world_state"].config[
            "audience_decision_model"
        ].value = False
    elif mode == "disabled":
        c.service.enabled = False
    names, _ = await reference_names(c, monkeypatch, consumer, "Mara said: I will go.")
    assert names == expected
    assert len(c.provider.calls) == (mode in {"uncertain", "failed"})
    if mode == "failed":
        record = next(iter(c.service.log.records.values()))
        assert record.status == "failed" and record.actions[0].status == "completed"


@pytest.mark.parametrize("consumer", ["memory", "snapshot"])
async def test_mixed_reference_answers(cast, monkeypatch, consumer):
    c = cast
    c.provider.answers = {
        "Mara": {"type": "noul", "p_true": 0.99},
        "Will": {"type": "noul", "p_true": 0.5},
    }
    names, _ = await reference_names(
        c, monkeypatch, consumer, "The innkeeper greets Will."
    )
    assert names == ["Mara", "Will"]
    record = next(iter(c.service.log.records.values()))
    assert record.actions[0].result["fallback_ids"] == ["Will"]


async def test_entity_visibility_filter_still_applies(cast, monkeypatch):
    c = cast
    c.provider.answers = {
        "Mara": {"type": "noul", "p_true": 0.99},
        "Will": {"type": "noul", "p_true": 0.01},
    }
    fetch = AsyncMock(
        return_value={
            "Mara.description": MemoryDocument(
                "private", meta={}, id="Mara.description", raw="private"
            )
        }
    )
    monkeypatch.setattr(c.memory, "get_documents_by_meta", fetch)
    result = await c.agent.entity_lookup(
        ["The innkeeper waves."], viewer="Player", filter=lambda doc: False
    )
    assert result == []
    assert fetch.call_args.kwargs == {"viewer": "Player"}


@pytest.mark.parametrize("consumer", ["memory", "snapshot"])
@pytest.mark.parametrize("result", ["", '{{ note("include", "confident") }}'])
async def test_reference_policy_without_result_uses_original_matcher(
    cast, monkeypatch, tmp_path, consumer, result
):
    from talemate.prompts.base import PrependTemplateDirectories

    name = (
        "decision-entity-references"
        if consumer == "memory"
        else "decision-snapshot-references"
    )
    (tmp_path / f"{name}.jinja2").write_text(result)
    with PrependTemplateDirectories(str(tmp_path)):
        names, _ = await reference_names(
            cast, monkeypatch, consumer, "Will waits outside."
        )
    assert names == ["Will"]
    assert not cast.provider.calls
    record = next(iter(cast.service.log.records.values()))
    assert record.failure.code == "result"
    assert len(record.actions) == 1
