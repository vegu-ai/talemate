from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from talemate.agents.context import ActiveAgent
from talemate.agents.memory.schema import MemoryDocument
from talemate.character import Character
from talemate.context import ActiveScene
from talemate.instance import get_agent
from talemate.history import ArchiveEntry
from talemate.knowledge.context import ContextHistoryMessage
from talemate.knowledge.formatting import perception_body
from talemate.knowledge.perspectives import set_source_perspectives, source_reference
from talemate.prompts import Prompt
from talemate.scene_message import CharacterMessage
from talemate.tale_mate import Actor
from talemate.util import count_tokens


def document(message_id, *, kind="message", text=None):
    text = text or f"MEMORY of passage {message_id}."
    return MemoryDocument(
        text,
        {"knowledge_kind": kind, "knowledge_id": str(message_id), "typ": "history"},
        f"view-{kind}-{message_id}",
        text,
    )


@pytest.fixture(params=["legacy", "perception"])
def cast(scene, monkeypatch, request):
    scene.knowledge_eligibility = request.param
    scene.rag_cache = {}
    conversation = get_agent("conversation")
    get_agent("summarizer").actions["manage_scene_history"].config[
        "format"
    ].value = "chat"
    conversation.actions["character_knowledge"].enabled = True
    conversation.actions["character_knowledge"].config["memory_pass"].value = False
    for name in ("Alice", "Bob"):
        character = Character(name=name, is_player=name == "Alice")
        actor = Actor(character, conversation)
        actor.scene = scene
        scene.actors.append(actor)
        scene.character_data[name] = character
    scene.active_characters = ["Alice", "Bob"]
    scene.history = [
        CharacterMessage(message=f"Alice: The lantern marks passage {i}.")
        for i in range(11)
    ]
    if request.param == "perception":
        for message in scene.history:
            set_source_perspectives(
                scene,
                "message",
                message.id,
                [
                    {
                        "audience": ["Alice", "Bob"],
                        "status": "ready",
                        "text": perception_body(message),
                    }
                ],
            )
    settings = get_agent("summarizer").actions["manage_scene_history"].config
    for key, value in {
        "best_fit": False,
        "dialogue_ratio": 100,
        "max_budget": 0,
        "enforce_boundary": False,
        "best_fit_min_dialogue": 0,
    }.items():
        settings[key].value = value
    monkeypatch.setattr(get_agent("memory"), "ensure_audience_index", AsyncMock())
    with ActiveScene(scene):
        yield scene, conversation, scene.character_data["Bob"]


def history(scene, budget):
    return scene.context_history(stored_views=True, perspective="Bob", budget=budget)


def identities(parts):
    return [
        part.message_id for part in parts if isinstance(part, ContextHistoryMessage)
    ]


@pytest.mark.parametrize("best_fit", [False, True])
async def test_ten_rendered_messages_are_excluded_and_older_memory_survives(
    cast, best_fit
):
    scene, conversation, bob = cast
    get_agent("summarizer").actions["manage_scene_history"].config[
        "best_fit"
    ].value = best_fit
    budget = count_tokens(scene.history[1:])
    selected = history(scene, budget)
    assert identities(selected) == [message.id for message in scene.history[1:]]
    candidates = [document(message.id) for message in scene.history]
    untouched = [
        document(scene.history[-1].id, kind=kind)
        for kind in ("fact", "summary", "disclosure", "authored")
    ]
    candidates.extend(untouched)
    original = [(str(item), dict(item.meta)) for item in candidates]
    result = await conversation.rag_exclude_context_history(candidates, selected)
    assert result == [candidates[0], *untouched]
    assert [(str(item), item.meta) for item in candidates] == original
    assert identities(deepcopy(selected)) == identities(selected)
    assert identities(selected) == [message.id for message in scene.history[1:]]


async def test_window_filter_preserves_raw_cache_when_history_shrinks(cast):
    scene, conversation, bob = cast
    candidates = [document(message.id) for message in scene.history]
    await conversation.rag_set_cache(candidates, bob)
    wide = history(scene, count_tokens(scene.history[1:]))
    narrow = history(scene, count_tokens(scene.history[-2:]))
    cache = dict(scene.rag_cache)
    fingerprint = scene.history[-1].fingerprint
    assert (
        await conversation.rag_exclude_context_history(candidates, wide)
        == candidates[:1]
    )
    assert (
        await conversation.rag_exclude_context_history(candidates, narrow)
        == candidates[:-2]
    )
    assert await conversation.rag_get_cache(bob) == candidates
    assert scene.history[-1].fingerprint == fingerprint
    assert scene.rag_cache == cache


async def test_filter_tracks_same_boundary_different_members_and_rewrites(cast):
    scene, conversation, bob = cast
    selected = history(scene, 10000)
    subset = [selected[0], *selected[2:]]
    omitted = document(scene.history[1].id)
    old = document(-1, text="Older rewrite")
    new = document(-1, text="Newer rewrite")
    assert await conversation.rag_exclude_context_history([omitted, old], selected) == [
        old
    ]
    assert await conversation.rag_exclude_context_history([omitted, new], subset) == [
        omitted,
        new,
    ]
    assert await conversation.rag_exclude_context_history([omitted, new], selected) == [
        new
    ]


async def test_hidden_messages_and_identical_text_keep_distinct_source_ids(cast):
    scene, conversation, bob = cast
    hidden = scene.history[5]
    hidden.hide()
    selected = history(scene, 10000)
    assert hidden.id not in identities(selected)
    candidates = [
        document(hidden.id, text="Same text"),
        document(scene.history[-1].id, text="Same text"),
        "Same text",
    ]
    filtered = await conversation.rag_exclude_context_history(candidates, selected)
    assert len(filtered) == 2
    assert filtered[0].meta["knowledge_id"] == str(hidden.id)
    assert type(filtered[1]) is str


async def test_empty_window_keeps_all_candidates(cast):
    scene, conversation, bob = cast
    candidates = [document(message.id) for message in scene.history]
    selected = history(scene, 0)
    assert selected == []
    assert (
        await conversation.rag_exclude_context_history(candidates, selected)
        == candidates
    )


async def test_summary_does_not_mark_its_underlying_messages_as_rendered(cast):
    scene, conversation, bob = cast
    scene.archived_history = [
        ArchiveEntry(
            id="past", text="The earlier lantern passages.", start=0, end=7
        ).model_dump(exclude_none=True)
    ]
    if scene.knowledge_eligibility == "perception":
        set_source_perspectives(
            scene,
            "summary",
            "past",
            [
                {
                    "audience": ["Alice", "Bob"],
                    "status": "ready",
                    "text": "Their earlier lantern passages.",
                    "sources": [
                        source_reference(scene, "message", message.id)
                        for message in scene.history[:8]
                    ],
                }
            ],
        )
    get_agent("summarizer").actions["manage_scene_history"].config[
        "dialogue_ratio"
    ].value = 30
    selected = history(scene, 100)
    assert any("earlier lantern passages" in part for part in selected)
    assert identities(selected) == [message.id for message in scene.history[8:]]
    candidates = [document(message.id) for message in scene.history]
    assert (
        await conversation.rag_exclude_context_history(candidates, selected)
        == candidates[:8]
    )


async def test_ai_rewritten_candidate_retains_source_for_post_filter(cast, monkeypatch):
    scene, conversation, bob = cast
    stored_fact = document(-1, kind="fact", text="The original fact wording")
    stored_fact.meta["typ"] = "fact"
    candidates = [document(scene.history[-1].id), stored_fact]
    request = AsyncMock(
        return_value=(
            "",
            {
                "none": None,
                "items": [
                    {"type": "item", "n": "1", "content": "Rewritten recent memory"},
                    {"type": "item", "n": "2", "content": "Rewritten old memory"},
                ],
            },
        )
    )
    monkeypatch.setattr(Prompt, "request", request)
    monkeypatch.setattr(
        get_agent("memory"), "audience_character_context", AsyncMock(return_value="")
    )
    refined = await conversation.memory_pass(bob, candidates)
    assert all(isinstance(item, MemoryDocument) for item in refined)
    assert refined[0].meta == candidates[0].meta
    assert refined[0].raw == candidates[0].raw
    result = await conversation.rag_exclude_context_history(
        refined, history(scene, 10000)
    )
    assert result == ["Rewritten old memory"]
    repeated = await conversation.rag_exclude_context_history(
        refined, history(scene, 10000)
    )
    assert repeated == ["Rewritten old memory"]
    assert repeated[0] is refined[1]
    assert not scene.rag_cache
    request.assert_awaited_once()


async def test_prompt_filters_after_one_history_selection_without_refetch(
    cast, monkeypatch
):
    scene, conversation, bob = cast
    settings = get_agent("summarizer").actions["manage_scene_history"].config
    settings["max_budget"].value = count_tokens(scene.history[1:])
    candidates = [document(message.id) for message in scene.history]
    retrieval = AsyncMock(return_value=candidates)
    monkeypatch.setattr(conversation, "rag_build", retrieval)
    calls = []
    select_history = scene.context_history

    def select(*args, **kwargs):
        result = select_history(*args, **kwargs)
        if kwargs.get("stored_views"):
            assert retrieval.await_count == 1
            calls.append((kwargs, list(result)))
        return result

    monkeypatch.setattr(scene, "context_history", select)
    with ActiveAgent(conversation, conversation.build_prompt_default):
        prompt = await conversation.build_prompt_default(bob)
        rendered = prompt.render()
    retrieval.assert_awaited_once()
    assert len(calls) == 1
    assert identities(calls[0][1]) == [message.id for message in scene.history[1:]]
    assert str(candidates[0]) in rendered
    for candidate in candidates[1:]:
        assert str(candidate) not in rendered
    for line in calls[0][1]:
        assert line in rendered
    assert len(candidates) == 11


async def test_filter_never_grows_cache_across_turns(cast):
    scene, conversation, bob = cast
    candidates = [document(message.id) for message in scene.history]
    await conversation.rag_set_cache(candidates, bob)
    cache = dict(scene.rag_cache)
    for turn in range(100):
        message = CharacterMessage(message=f"Bob: New turn {turn}.")
        scene.history.append(message)
        selected = [ContextHistoryMessage(str(message), message.id)]
        current = document(message.id)
        assert (
            await conversation.rag_exclude_context_history(
                [*candidates, current], selected
            )
            == candidates
        )
        assert scene.rag_cache == cache


@pytest.mark.parametrize("cast", ["perception"], indirect=True)
async def test_director_guidance_excludes_its_rendered_evidence_window(
    cast, monkeypatch
):
    from talemate.knowledge.advice import advice_context

    scene, conversation, bob = cast
    director = get_agent("director")
    director.connect(scene)
    evidence = advice_context(scene, bob, 3 * count_tokens(scene.history[1:]))
    assert identities(evidence["history"]) == [
        message.id for message in scene.history[1:]
    ]
    candidates = [document(message.id) for message in scene.history]
    retrieval = AsyncMock(return_value=candidates)
    monkeypatch.setattr(director, "rag_build", retrieval)
    with ActiveAgent(director, director.guide_actor_off_of_scene_analysis):
        rendered = Prompt.get(
            "director.guide-conversation",
            vars={
                "scene": scene,
                "character": bob,
                "evidence": evidence,
                "analysis": "",
                "length": 100,
            },
        ).render()
    retrieval.assert_awaited_once()
    assert str(candidates[0]) in rendered
    assert all(str(item) not in rendered for item in candidates[1:])
    assert all(str(part) in rendered for part in evidence["history"])


@pytest.mark.parametrize("cast", ["perception"], indirect=True)
@pytest.mark.parametrize("method", ["queries", "questions"])
@pytest.mark.parametrize("include_raw", [False, True])
async def test_ai_retrieval_excludes_prompt_window_from_extra_context(
    cast, monkeypatch, method, include_raw
):
    scene, conversation, bob = cast
    selected = history(scene, count_tokens(scene.history[1:]))
    candidates = [document(message.id) for message in scene.history]
    fact = document(scene.history[-1].id, kind="fact")
    candidates.append(fact)
    semantic = AsyncMock(return_value=candidates)
    monkeypatch.setattr(conversation, "semantic_context", semantic)
    monkeypatch.setattr(
        conversation, "rag_projected_history", lambda *a, **kw: selected
    )
    world_state = get_agent("world_state")
    analysis = AsyncMock(
        return_value="Synthesized older memory"
        if method == "questions"
        else ["Synthesized older memory"]
    )
    action = "analyze_text_and_extract_context" + (
        "_via_queries" if method == "queries" else ""
    )
    monkeypatch.setattr(world_state, action, analysis)
    result = await conversation._rag_build(
        bob, retrieval_method=method, include_raw_semantic=include_raw
    )
    semantic.assert_awaited_once()
    analysis.assert_awaited_once()
    assert analysis.call_args.args[0] == "\n".join(selected)
    assert analysis.call_args.kwargs["extra_context"] == [candidates[0], fact]
    assert "Synthesized older memory" in result
    if include_raw:
        assert all(candidate in result for candidate in candidates)
    else:
        assert result == ["Synthesized older memory"]
