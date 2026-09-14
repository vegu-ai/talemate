import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from talemate.context import ActiveScene
from talemate.character import Character
from talemate.instance import get_agent
from talemate.scene_message import CharacterMessage
from talemate.knowledge.schema import Fact
from talemate.prompts import Prompt

CASES = json.loads(
    (Path(__file__).parent / "data/knowledge_ledger/situational.json").read_text()
)


def ledger_variables(scene, case):
    return dict(
        scene=scene,
        speaker=case["speaker"],
        listeners=case["listeners"],
        recent_lines=case["recent_lines"],
        line=case["line"],
        absence={case["listeners"]: [Fact(id="F1", text=case["fact"])]},
    )


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_ledger_situational_prompt_contract(scene, case):
    with ActiveScene(scene):
        rendered = Prompt.get(
            "conversation.knowledge-ledger", vars=ledger_variables(scene, case)
        ).render()
    assert "conveys its substance" in rendered
    assert "RECENT LINES and the situation" in rendered
    assert "unless that detail is the point of the fact" in rendered
    assert "Lean toward learning" in rendered
    assert "Learned example" in rendered and "Not learned example" in rendered
    assert '<LEDGER>{"Mara": ["F1"]}</LEDGER>' in rendered
    assert "Elmer saw something on my screen. Guess what?" in rendered
    assert "Answer <LEDGER>{}</LEDGER> when nobody learned anything." in rendered
    assert "value the list of fact ids they learned" in rendered
    assert case["line"] in rendered
    assert all(line in rendered for line in case["recent_lines"])
    assert "<FACTS>" not in rendered


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
async def test_situational_ledger_answers_apply_only_expected_grants(
    scene, case, monkeypatch
):
    conversation = get_agent("conversation")
    scene.knowledge_eligibility = "legacy"
    scene.active_characters = [case["speaker"], case["listeners"]]
    scene.character_data = {
        name: Character(name=name) for name in scene.active_characters
    }
    scene.ts = 500
    scene.history = [CharacterMessage(message=line) for line in case["recent_lines"]]
    fact = Fact(id="F1", text=case["fact"], ts=490, present=[case["speaker"]])
    scene.world_state.facts = {fact.id: fact}
    action = conversation.actions["character_knowledge"]
    action.enabled = True
    action.config["ledger"].value = True

    async def answer(*args, **kwargs):
        variables = kwargs["vars"]
        assert variables["line"] == case["line"]
        assert variables["recent_lines"] == case["recent_lines"]
        assert variables["absence"] == {case["listeners"]: [fact]}
        # Mock only the model boundary; run the shipped extraction and grant path.
        response = "<LEDGER>" + json.dumps(case["expected"]) + "</LEDGER>"
        return response, kwargs["response_spec"].extract_all(response)

    request = AsyncMock(side_effect=answer)
    monkeypatch.setattr(Prompt, "request", request)
    with ActiveScene(scene):
        learned = await conversation.record_learned_facts(
            scene.character_data[case["speaker"]], case["line"]
        )
    request.assert_awaited_once()
    assert learned == case["expected"]
    expected_names = list(case["expected"])
    assert fact.known_by == {name: "inferred" for name in expected_names}
    assert [
        (edge.character, edge.target, edge.kind, edge.source)
        for edge in scene.world_state.knowledge
    ] == [(name, "F1", "grant", "inferred") for name in expected_names]
