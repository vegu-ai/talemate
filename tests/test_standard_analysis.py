from unittest.mock import AsyncMock, Mock

import pytest

from conftest import MockScene, bootstrap_scene
from talemate.agents.context import ActiveAgent
from talemate.agents.conversation import ConversationAgentEmission
from talemate.agents.editor.revision import Issues, RevisionInformation
from talemate.character import Character
from talemate.context import ActiveScene
from talemate.instance import get_agent
from talemate.knowledge.schema import Fact, KnowledgeEdge
from talemate.knowledge.standard_analysis import (
    standard_analysis_context,
    standard_analysis_enabled,
)
from talemate.prompts import Prompt
from talemate.scene_message import CharacterMessage
from talemate.util import count_tokens


@pytest.fixture
def standard_scene(monkeypatch):
    scene = MockScene()
    agents = bootstrap_scene(scene)
    scene.character_data = {
        name: Character(name=name, description=f"{name} lives at the lighthouse.")
        for name in ["Alice", "Bob"]
    }
    scene.history = [
        CharacterMessage(message="Alice: Welcome back.", present=["Alice", "Bob"])
    ]
    scene.world_state.facts = {
        "F1": Fact(id="F1", text="OLDER_KNOWN", ts=10, present=["Bob"]),
        "F2": Fact(id="F2", text="NEWER_KNOWN", ts=20, present=["Bob"]),
        "F3": Fact(id="F3", text="UNKNOWN_SECRET", ts=30, present=["Alice"]),
    }
    summarizer = agents["summarizer"]
    monkeypatch.setattr(summarizer, "rag_build", AsyncMock(return_value=[]))
    with ActiveScene(scene), ActiveAgent(summarizer, standard_scene):
        yield scene, summarizer, scene.character_data["Bob"]


@pytest.fixture
def captured_prompt(monkeypatch):
    prompts = []

    async def request(template, client, kind, vars, **kwargs):
        prompts.append((vars, Prompt.get(template, vars=vars).render()))
        return "", {"analysis": "Bob can ask Alice what happened.", "investigate": ""}

    mock = AsyncMock(side_effect=request)
    monkeypatch.setattr(Prompt, "request", mock)
    return prompts, mock


async def test_analysis_includes_character_knowledge_without_another_request(
    standard_scene, captured_prompt
):
    scene, summarizer, bob = standard_scene
    prompts, request = captured_prompt
    await summarizer.analyze_scene_for_next_action("conversation", bob)
    request.assert_awaited_once()
    vars, prompt = prompts[0]
    assert vars["evidence"] is None
    assert "Known facts for Bob" in prompt
    assert prompt.index("NEWER_KNOWN") < prompt.index("OLDER_KNOWN")
    assert "Unknown recent facts for Bob" in prompt
    assert "UNKNOWN_SECRET" in prompt
    assert "Ground awareness in Known facts" in prompt
    assert "cannot guide their actions" in prompt
    assert "Facts are sourced from the existing story, don't assume" in prompt


async def test_analysis_lists_the_unknown_facts_before_the_other_points(
    standard_scene, captured_prompt
):
    # #605: the analysis states what Bob does not know before it writes about
    # what the others need to tell him
    scene, summarizer, bob = standard_scene
    prompts, _ = captured_prompt
    await summarizer.analyze_scene_for_next_action("conversation", bob)
    _, prompt = prompts[0]
    listing = prompt.index("1. First, list what Bob does not know")
    assert listing < prompt.index("2. Briefly make statements about context")
    assert prompt.index("Unknown recent facts for Bob") < listing
    assert 'write it as "(unknown to Bob)"' in prompt
    assert "anything said in the scene while Bob was absent" in prompt

    scene.world_state.facts.clear()
    await summarizer.analyze_scene_for_next_action("conversation", bob)
    variables, prompt = prompts[1]
    assert variables["standard_knowledge"] is None
    assert "does not know" not in prompt
    assert "(unknown to Bob)" not in prompt
    assert prompt.index("1. Briefly make statements about context") >= 0


@pytest.mark.parametrize("target", ["Bob", "Alice"])
async def test_unslop_prompt_keeps_targeted_standard_analysis(
    standard_scene, monkeypatch, target
):
    scene, summarizer, bob = standard_scene
    editor = get_agent("editor")
    await summarizer.set_cached_analysis("conversation", "BOB_ANALYSIS", bob)
    monkeypatch.setattr(
        editor, "revision_collect_issues", AsyncMock(return_value=Issues())
    )
    prompts = []

    async def request(template, client, kind, vars, **kwargs):
        prompts.append(Prompt.get(template, vars=vars).render())
        return "", {"fix": ""}

    monkeypatch.setattr(Prompt, "request", AsyncMock(side_effect=request))
    await editor.revision_unslop(
        RevisionInformation(
            text=f"{target}: Hello.", character=scene.character_data[target]
        )
    )
    assert ("BOB_ANALYSIS" in prompts[0]) == (target == "Bob")


async def test_empty_fact_index_matches_disabled_prompt(
    standard_scene, captured_prompt
):
    scene, summarizer, bob = standard_scene
    scene.world_state.facts.clear()
    await summarizer.analyze_scene_for_next_action("conversation", bob)
    variables, enabled_prompt = captured_prompt[0][0]
    assert variables["standard_knowledge"] is None
    get_agent("conversation").actions["character_knowledge"].enabled = False
    await summarizer.analyze_scene_for_next_action("conversation", bob)
    assert enabled_prompt == captured_prompt[0][1][1]


async def test_no_fact_lines_fit_omits_blocks(standard_scene):
    scene, _, bob = standard_scene
    assert await standard_analysis_context(scene, bob, 0) is None


async def test_unknown_only_block_does_not_blame_budget(standard_scene):
    scene, _, bob = standard_scene
    for fact in scene.world_state.facts.values():
        fact.present = ["Alice"]
    context = await standard_analysis_context(scene, bob, 900)
    assert "No recorded facts for this character." in context["text"]
    assert "No recorded known facts fit this budget." not in context["text"]
    assert "UNKNOWN_SECRET" in context["text"]


async def test_dialogue_subswitches_do_not_gate_analysis(
    standard_scene, captured_prompt
):
    _, summarizer, bob = standard_scene
    action = get_agent("conversation").actions["character_knowledge"]
    action.config["perspective_filter"].value = False
    action.config["absence_block"].value = False
    await summarizer.analyze_scene_for_next_action("conversation", bob)
    assert captured_prompt[0][0][0]["standard_knowledge"] is not None


@pytest.mark.parametrize("disabled", ["master", "narration", "perspectives"])
async def test_gate_does_not_read_standard_knowledge(
    standard_scene, captured_prompt, monkeypatch, disabled
):
    scene, summarizer, bob = standard_scene
    if disabled == "master":
        get_agent("conversation").actions["character_knowledge"].enabled = False
    if disabled == "perspectives":
        scene.knowledge_eligibility = "perception"
    typ = "narration" if disabled == "narration" else "conversation"
    assert not standard_analysis_enabled(scene, bob, typ)
    if disabled == "perspectives":
        return
    read = AsyncMock(side_effect=AssertionError("standard facts read while disabled"))
    monkeypatch.setattr(
        "talemate.agents.summarize.analyze_scene.standard_analysis_context", read
    )
    await summarizer.analyze_scene_for_next_action(typ, bob)
    read.assert_not_awaited()
    vars, text = captured_prompt[0][0]
    assert vars["standard_knowledge"] is None
    assert "Known facts for" not in text
    assert "UNKNOWN_SECRET" not in text
    if disabled == "master":
        assert "Facts are sourced from the existing story, don't assume" in text


async def test_context_budget_and_recent_unknown_settings(standard_scene):
    scene, _, bob = standard_scene
    scene.world_state.facts["F2"].text = "huge " * 1000
    scene.world_state.facts["F4"] = Fact(
        id="F4", text="LATEST_SECRET", ts=40, present=["Alice"]
    )
    action = get_agent("conversation").actions["character_knowledge"]
    action.config["absence_window"].value = 1
    action.config["absence_limit"].value = 1
    context = await standard_analysis_context(scene, bob, 90)
    assert "huge" not in context["text"]
    assert "OLDER_KNOWN" in context["text"]
    assert "LATEST_SECRET" in context["text"]
    assert "UNKNOWN_SECRET" not in context["text"]
    assert context["tokens"] == count_tokens(context["text"])


async def test_fact_blocks_reserve_history_budget(
    standard_scene, captured_prompt, monkeypatch
):
    scene, summarizer, bob = standard_scene
    history = Mock(return_value=["A lighthouse."])
    monkeypatch.setattr(scene, "context_history", history)
    await summarizer.analyze_scene_for_next_action("conversation", bob)
    limited_budget = history.call_args.kwargs["budget"]
    knowledge_tokens = captured_prompt[0][0][0]["standard_knowledge"]["tokens"]
    get_agent("conversation").actions["character_knowledge"].enabled = False
    await summarizer.analyze_scene_for_next_action("conversation", bob)
    assert history.call_args.kwargs["budget"] - limited_budget == knowledge_tokens


async def test_grant_and_revoke_move_facts_between_blocks(standard_scene):
    scene, _, bob = standard_scene
    scene.world_state.knowledge = [
        KnowledgeEdge(character="Bob", target="F3", kind="grant"),
        KnowledgeEdge(character="Bob", target="F2", kind="revoke"),
    ]
    context = await standard_analysis_context(scene, bob, 900)
    known, unknown = context["text"].split("<|SECTION:UNKNOWN RECENT FACTS|>")
    assert "UNKNOWN_SECRET" in known and "UNKNOWN_SECRET" not in unknown
    assert "NEWER_KNOWN" in unknown and "NEWER_KNOWN" not in known


@pytest.mark.parametrize("when", ["request", "emit"])
@pytest.mark.parametrize("change_kind", ["fact", "enable_master"])
async def test_knowledge_edit_does_not_cancel_standard_generation(
    standard_scene, captured_prompt, monkeypatch, when, change_kind
):
    scene, summarizer, bob = standard_scene
    summarizer.actions["analyze_scene"].enabled = True
    knowledge = get_agent("conversation").actions["character_knowledge"]
    if change_kind == "enable_master":
        knowledge.enabled = False

    async def change(*args, **kwargs):
        if change_kind == "enable_master":
            knowledge.enabled = True
        else:
            scene.world_state.facts["F3"].present = ["Alice", "Bob"]
        return "", {"analysis": "Completed analysis.", "investigate": ""}

    if when == "request":
        monkeypatch.setattr(Prompt, "request", AsyncMock(side_effect=change))
    else:
        monkeypatch.setattr(summarizer, "emit_message", AsyncMock(side_effect=change))
    emission = ConversationAgentEmission(
        agent=summarizer, response="", actor=None, character=bob
    )
    await summarizer.on_inject_instructions(emission)
    assert any(item.title == "Scene Analysis" for item in emission.dynamic_instructions)
    assert await summarizer.get_cached_analysis("conversation", bob) is None


@pytest.mark.parametrize(
    "change",
    [
        "new_fact",
        "fact_text",
        "presence",
        "ledger",
        "allow",
        "block",
        "master",
        "window",
        "limit",
        "character",
        "scene_time",
        "active_characters",
        "milestone_half_life",
        "state_half_life",
        "routine_half_life",
        "recent_window",
        "score_floor",
    ],
)
async def test_cached_analysis_invalidates_on_knowledge_changes(standard_scene, change):
    scene, summarizer, bob = standard_scene
    await summarizer.set_cached_analysis("conversation", "BOB_ANALYSIS", bob)
    assert await summarizer.get_cached_analysis("conversation", bob) == "BOB_ANALYSIS"
    if change == "new_fact":
        scene.world_state.facts["F4"] = Fact(id="F4", text="NEW_FACT", present=["Bob"])
    elif change == "fact_text":
        scene.world_state.facts["F1"].text = "Changed known fact"
    elif change == "presence":
        scene.world_state.facts["F3"].present = ["Alice", "Bob"]
    elif change == "ledger":
        scene.world_state.facts["F3"].known_by["Bob"] = "told"
        scene.world_state.knowledge.append(
            KnowledgeEdge(character="Bob", target="F3", kind="grant")
        )
    elif change in ["allow", "block"]:
        scene.world_state.knowledge.append(
            KnowledgeEdge(
                character="Bob",
                target="F3" if change == "allow" else "F1",
                kind="grant" if change == "allow" else "revoke",
            )
        )
    elif change == "master":
        get_agent("conversation").actions["character_knowledge"].enabled = False
    elif change in ["window", "limit"]:
        get_agent("conversation").actions["character_knowledge"].config[
            f"absence_{change}"
        ].value += 1
    elif change == "character":
        bob = scene.character_data["Alice"]
    elif change == "scene_time":
        scene.ts += 1
    elif change == "active_characters":
        scene.active_characters = ["Alice"]
    else:
        summarizer.actions["fact_chronology"].config[change].value += 1
    assert await summarizer.get_cached_analysis("conversation", bob) is None


async def test_narration_cache_ignores_standard_fact_changes(standard_scene):
    scene, summarizer, _ = standard_scene
    await summarizer.set_cached_analysis("narration", "AUTHOR_ANALYSIS")
    scene.world_state.facts["F1"].text = "Changed known fact"
    assert await summarizer.get_cached_analysis("narration") == "AUTHOR_ANALYSIS"
