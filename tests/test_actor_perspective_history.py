from unittest.mock import AsyncMock, Mock

import pytest

from talemate.agents.context import ActiveAgent
from talemate.agents.editor.revision import Issues, RevisionContext, RevisionInformation
from talemate.character import Character
from talemate.context import ActiveScene
from talemate.exceptions import GenerationCancelled
from talemate.instance import get_agent
from talemate.knowledge.context import project_character_history
from talemate.knowledge.perspectives import set_source_perspectives
from talemate.prompts import Prompt
from talemate.scene_message import CharacterMessage, DirectorMessage, NarratorMessage
from talemate.tale_mate import Actor

PRIVATE = "Alice remembers the sapphire hidden in her boot."
PUBLIC = '"The rain has stopped."'
PUBLIC_SCRIPT = '\nALICE\n"The rain has stopped."\nEND-OF-LINE\n'
ALICE_SCRIPT = "\nALICE\n" + PRIVATE + " " + PUBLIC + "\nEND-OF-LINE\n"
READER = "Alice: The sapphire is hidden in her boot. She says the rain has stopped."


@pytest.fixture
def cast(scene, monkeypatch):
    scene.knowledge_eligibility = "perception"
    conversation = get_agent("conversation")
    for name in ("Alice", "Bob", "Cara"):
        character = Character(name=name, is_player=name == "Alice")
        actor = Actor(character, conversation)
        actor.scene = scene
        scene.actors.append(actor)
        scene.character_data[name] = character
    scene.active_characters = ["Alice", "Bob", "Cara"]
    mixed = CharacterMessage(message=READER, present=["Alice", "Bob", "Cara"])
    omitted = NarratorMessage(message="UNSEEN-VAULT-CODE")
    untracked = NarratorMessage(message="UNTRACKED-PRIVATE-HISTORY")
    scene.history = [mixed, omitted, untracked]
    set_source_perspectives(
        scene,
        "message",
        mixed.id,
        [
            {
                "audience": ["Alice"],
                "status": "ready",
                "text": "Alice: " + PRIVATE + " " + PUBLIC,
            },
            {
                "audience": ["Bob", "Cara"],
                "status": "ready",
                "text": "Alice: " + PUBLIC,
            },
        ],
    )
    set_source_perspectives(
        scene,
        "message",
        omitted.id,
        [
            {"audience": ["Alice", "Bob", "Cara"], "status": "omitted"},
        ],
    )
    monkeypatch.setattr(conversation, "rag_build", AsyncMock(return_value=[]))
    monkeypatch.setattr(get_agent("editor"), "rag_build", AsyncMock(return_value=[]))
    with ActiveScene(scene):
        yield scene, mixed


@pytest.mark.parametrize("best_fit", [False, True])
def test_projection_replaces_history_without_intro_or_summary_fallback(cast, best_fit):
    scene, _ = cast
    summarizer = get_agent("summarizer")
    summarizer.actions["manage_scene_history"].config["best_fit"].value = best_fit
    scene.intro = "INTRO-PRIVATE"
    scene.archived_history = [
        {"id": "archive", "text": "SUMMARY-PRIVATE", "start": 0, "end": 0, "ts": 0}
    ]
    scene.layered_history = [
        [{"id": "layer", "text": "LAYER-PRIVATE", "start": 0, "end": 0, "ts": 0}]
    ]
    assert scene.context_history(stored_views=True, budget=1000, perspective="Bob") == [
        PUBLIC_SCRIPT
    ]
    assert scene.context_history(
        stored_views=True, budget=1000, perspective="Cara"
    ) == [PUBLIC_SCRIPT]
    assert scene.context_history(
        stored_views=True, budget=1000, perspective="Alice"
    ) == [ALICE_SCRIPT]
    assert READER.split(": ", 1)[1] in "\n".join(
        scene.context_history(stored_views=True, budget=100000)
    )
    assert scene.history[0].message == READER


def test_projection_budget_counts_replacement_and_keeps_reader_immutable(
    cast, monkeypatch
):
    scene, mixed = cast
    original = mixed.model_dump()
    monkeypatch.setattr("talemate.knowledge.context.count_tokens", len)
    assert project_character_history(scene, "Bob", budget=len(PUBLIC_SCRIPT)) == [
        PUBLIC_SCRIPT
    ]
    assert project_character_history(scene, "Alice", budget=len(PUBLIC_SCRIPT)) == []
    assert project_character_history(scene, "Bob", budget=0) == []
    assert project_character_history(scene, "Bob", max_messages=0) == []
    assert mixed.model_dump() == original


@pytest.mark.parametrize("status", ["pending", "failed"])
def test_nonready_projection_blocks_without_reader_fallback(cast, status):
    scene, mixed = cast
    set_source_perspectives(
        scene, "message", mixed.id, [{"audience": ["Bob"], "status": status}]
    )
    expected = "failed" if status == "failed" else "not run yet"
    with pytest.raises(GenerationCancelled, match=expected) as raised:
        scene.context_history(stored_views=True, budget=1000, perspective="Bob")
    assert raised.value.message_id == mixed.id
    assert raised.value.view_status == status
    assert raised.value.character == "Bob"


def test_stale_projection_blocks(cast):
    scene, mixed = cast
    scene.edit_message(mixed.id, "Alice: Changed reader text.")
    with pytest.raises(GenerationCancelled, match="not run yet"):
        project_character_history(scene, "Bob")


def test_missing_audience_is_absent(cast):
    scene, mixed = cast
    set_source_perspectives(
        scene,
        "message",
        mixed.id,
        [{"audience": ["Alice"], "status": "ready", "text": PRIVATE}],
    )
    assert project_character_history(scene, "Bob") == []


def test_projection_hidden_target_and_scoped_guidance(cast):
    scene, mixed = cast
    mixed.hide()
    assert project_character_history(scene, "Bob") == []
    assert project_character_history(scene, "Bob", show_hidden=True) == [PUBLIC_SCRIPT]
    assert (
        project_character_history(
            scene, "Bob", show_hidden=True, before_message_id=mixed.id
        )
        == []
    )
    with pytest.raises(GenerationCancelled, match="removed"):
        project_character_history(scene, "Bob", before_message_id=999999)
    scene.history.extend(
        [
            DirectorMessage(
                message="ALICE-ONLY-GUIDANCE",
                meta={"character": "Alice"},
            ),
            DirectorMessage(message="BOB-ONLY-GUIDANCE", meta={"character": "Bob"}),
        ]
    )
    text = "\n".join(project_character_history(scene, "Bob", keep_director=True))
    assert "BOB-ONLY-GUIDANCE" in text
    assert "ALICE-ONLY-GUIDANCE" not in text


def test_legacy_and_reader_paths_stay_complete(cast):
    scene, _ = cast
    scene.knowledge_eligibility = "legacy"
    text = "\n".join(scene.context_history(stored_views=True, budget=100000))
    assert READER.split(": ", 1)[1] in text
    assert "UNTRACKED-PRIVATE-HISTORY" in text
    with pytest.raises(ValueError, match="perception mode"):
        project_character_history(scene, "Bob")


@pytest.mark.asyncio
async def test_rendered_actor_prompts_differ_and_shared_views_match(cast):
    scene, _ = cast
    conversation = get_agent("conversation")
    conversation.actions["character_knowledge"].enabled = False
    rendered = {}
    for name in ("Alice", "Bob", "Cara"):
        with ActiveAgent(conversation, conversation.build_prompt_default):
            prompt = await conversation.build_prompt_default(scene.character_data[name])
            rendered[name] = prompt.render()
    assert PRIVATE in rendered["Alice"]
    assert "sapphire" not in rendered["Bob"] and "sapphire" not in rendered["Cara"]
    for name, prompt in rendered.items():
        assert (ALICE_SCRIPT if name == "Alice" else PUBLIC_SCRIPT) in prompt
        assert "UNSEEN-VAULT-CODE" not in prompt
        assert "UNTRACKED-PRIVATE-HISTORY" not in prompt
        assert READER not in prompt
    assert scene.context_history(
        stored_views=True, budget=1000, perspective="Bob"
    ) == scene.context_history(stored_views=True, budget=1000, perspective="Cara")


@pytest.mark.asyncio
async def test_pending_lifecycle_stops_actor_request(cast, monkeypatch):
    scene, _ = cast
    conversation = get_agent("conversation")
    ensure = AsyncMock(side_effect=GenerationCancelled("Analysis cancelled"))
    monkeypatch.setattr(get_agent("summarizer"), "ensure_perceptions", ensure)
    send = AsyncMock()
    monkeypatch.setattr(Prompt, "send", send)
    with pytest.raises(GenerationCancelled):
        await conversation.converse(scene.character_data["Bob"].actor)
    ensure.assert_awaited_once_with(scene)
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_repetition_corpus_uses_reader_prose_and_revision_boundary(
    cast, monkeypatch
):
    scene, _ = cast
    editor = get_agent("editor")
    target = CharacterMessage(message="Bob: REVISION-TARGET")
    scene.history.append(target)
    scene.history.append(NarratorMessage(message="FUTURE-PRIVATE"))
    corpus = []

    def compare(text, prior, **kwargs):
        corpus.append(prior)
        return []

    monkeypatch.setattr("talemate.agents.editor.revision.similarity_matches", compare)
    with RevisionContext(target.id):
        await editor._revision_evaluate_fuzzy_similarity(
            target.message, scene.character_data["Bob"]
        )
    assert corpus == [
        "UNTRACKED-PRIVATE-HISTORY",
        "UNSEEN-VAULT-CODE",
        READER.split(":", 1)[1],
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["rewrite", "unslop"])
async def test_character_revision_renders_projected_history(cast, monkeypatch, method):
    scene, _ = cast
    editor = get_agent("editor")
    target = CharacterMessage(message="Bob: A candidate response.")
    scene.history.append(target)
    rendered = []
    cached = AsyncMock(return_value="OTHER-CHARACTER-PRIVATE-ANALYSIS")
    monkeypatch.setattr(get_agent("summarizer"), "get_cached_analysis", cached)
    editor.actions["revision"].config["min_issues"].value = 0
    monkeypatch.setattr(
        editor,
        "revision_collect_issues",
        AsyncMock(
            return_value=Issues(
                repetition_log=["Repeated public speech"],
                repetition=[
                    {"text_a": "candidate", "text_b": PRIVATE, "similarity": 100}
                ],
            )
        ),
    )

    async def request(template, client, kind, vars, **kwargs):
        rendered.append(Prompt.get(template, vars=vars).render())
        return "", {"revision": "A revised response.", "fix": "A revised response."}

    monkeypatch.setattr(Prompt, "request", request)
    fn = editor.revision_rewrite if method == "rewrite" else editor.revision_unslop
    with RevisionContext(target.id), ActiveAgent(editor, fn):
        await fn(
            RevisionInformation(
                text=target.message, character=scene.character_data["Bob"]
            )
        )
    assert len(rendered) == 1
    assert PUBLIC in rendered[0]
    assert PRIVATE not in rendered[0]
    assert "sapphire is hidden in her boot" not in rendered[0]
    assert "UNSEEN-VAULT-CODE" not in rendered[0]
    assert "UNTRACKED-PRIVATE-HISTORY" not in rendered[0]
    assert "OTHER-CHARACTER-PRIVATE-ANALYSIS" not in rendered[0]
    if method == "unslop":
        cached.assert_not_awaited()


@pytest.mark.asyncio
async def test_add_detail_renders_projected_history(cast, monkeypatch):
    scene, _ = cast
    editor = get_agent("editor")
    monkeypatch.setattr(type(editor), "add_detail_enabled", property(lambda self: True))
    rendered = []

    async def request(template, client, kind, vars, **kwargs):
        rendered.append(Prompt.get(template, vars=vars).render())
        return "", {"response": "Bob: The rain has stopped."}

    monkeypatch.setattr(Prompt, "request", request)
    with ActiveAgent(editor, editor.add_detail):
        await editor.add_detail("Bob: Hello.", scene.character_data["Bob"])
    assert PUBLIC in rendered[0]
    assert PRIVATE not in rendered[0]
    assert "sapphire is hidden in her boot" not in rendered[0]
    assert "UNSEEN-VAULT-CODE" not in rendered[0]


@pytest.mark.asyncio
async def test_pending_editor_analysis_prevents_request(cast, monkeypatch):
    scene, _ = cast
    editor = get_agent("editor")
    monkeypatch.setattr(type(editor), "add_detail_enabled", property(lambda self: True))
    monkeypatch.setattr(
        get_agent("summarizer"),
        "ensure_perceptions",
        AsyncMock(side_effect=GenerationCancelled("Retry required")),
    )
    request = AsyncMock()
    monkeypatch.setattr(Prompt, "request", request)
    with pytest.raises(GenerationCancelled):
        await editor.add_detail("Bob: Hello.", scene.character_data["Bob"])
    request.assert_not_awaited()


@pytest.mark.parametrize(
    "format,expected",
    [
        ("movie_script", PUBLIC_SCRIPT + "The door is open.\n"),
        ("ai_aware", PUBLIC_SCRIPT + "The door is open.\n"),
        ("chat", "Alice: " + PUBLIC + "The door is open."),
        ("narrative", PUBLIC + "The door is open."),
    ],
)
@pytest.mark.parametrize("prefixed", [True, False])
def test_projection_formats_source_speaker_and_passage_type(
    cast, monkeypatch, format, expected, prefixed
):
    scene, mixed = cast
    monkeypatch.setattr(
        type(scene), "conversation_format", property(lambda self: format)
    )
    set_source_perspectives(
        scene,
        "message",
        mixed.id,
        [
            {
                "audience": ["Bob"],
                "status": "ready",
                "text": ("Alice: " if prefixed else "") + PUBLIC,
            }
        ],
    )
    narrator = NarratorMessage(message="Reader-only door detail.")
    scene.history.append(narrator)
    set_source_perspectives(
        scene,
        "message",
        narrator.id,
        [{"audience": ["Bob"], "status": "ready", "text": "The door is open."}],
    )
    before = [message.model_dump() for message in scene.history]
    assert "".join(project_character_history(scene, "Bob")) == expected
    assert [message.model_dump() for message in scene.history] == before


@pytest.mark.parametrize(
    "mode,perspective,stored",
    [("legacy", "Bob", True), ("perception", None, True), ("perception", "Bob", False)],
)
def test_boundary_is_rejected_outside_stored_projection(
    cast, mode, perspective, stored
):
    scene, mixed = cast
    scene.knowledge_eligibility = mode
    with pytest.raises(ValueError, match="before_message_id requires"):
        scene.context_history(
            budget=1000,
            perspective=perspective,
            stored_views=stored,
            before_message_id=mixed.id,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["perception", "legacy"])
async def test_verbatim_repetition_survives_perception_paraphrasing(cast, mode):
    scene, mixed = cast
    scene.knowledge_eligibility = mode
    sentence = "The rain has stopped, and the courtyard smells of wet stone."
    scene.edit_message(mixed.id, "Alice: " + sentence)
    if mode == "perception":
        set_source_perspectives(
            scene,
            "message",
            mixed.id,
            [
                {
                    "audience": ["Bob"],
                    "status": "ready",
                    "text": "Alice: Bob notes the end of the rain and the courtyard's scent.",
                }
            ],
        )
    editor = get_agent("editor")
    editor.actions["revision"].config["repetition_min_length"].value = 20
    matches = await editor._revision_evaluate_fuzzy_similarity(
        sentence, scene.character_data["Bob"]
    )
    assert any(
        match.original.strip() == sentence and match.matched.strip() == sentence
        for match in matches
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["rewrite", "unslop"])
async def test_revision_falls_back_without_repairing_its_prefix(
    cast, monkeypatch, method
):
    scene, mixed = cast
    summarizer = get_agent("summarizer")
    editor = get_agent("editor")
    target = CharacterMessage(message="Bob: A candidate response.")
    later = NarratorMessage(message="Later failed passage.")
    scene.history.extend([target, later])
    for message in (mixed, target, later):
        set_source_perspectives(
            scene, "message", message.id, [{"audience": ["Bob"], "status": "failed"}]
        )
    analyzed = []

    async def analyze(scene, message):
        analyzed.append(message.id)
        assert message is mixed
        set_source_perspectives(
            scene,
            "message",
            message.id,
            [{"audience": ["Bob"], "status": "ready", "text": "Alice: " + PUBLIC}],
        )

    monkeypatch.setattr(summarizer, "analyze_perceptions", analyze)
    monkeypatch.setattr(
        editor,
        "revision_collect_issues",
        AsyncMock(
            return_value=Issues(repetition_log=["Revise this repeated sentence"])
        ),
    )
    rendered = []

    async def request(template, client, kind, vars, **kwargs):
        rendered.append(Prompt.get(template, vars=vars).render())
        return "", {"revision": "A revised response.", "fix": "A revised response."}

    monkeypatch.setattr(Prompt, "request", request)
    fn = editor.revision_rewrite if method == "rewrite" else editor.revision_unslop
    with RevisionContext(target.id), ActiveAgent(editor, fn):
        await fn(
            RevisionInformation(
                text=target.message, character=scene.character_data["Bob"]
            )
        )
    assert analyzed == []
    assert len(rendered) == 1
    assert READER.split(": ", 1)[1] in rendered[0]
    assert "Later failed passage" in rendered[0]
    assert "UNSEEN-VAULT-CODE" in rendered[0]
    assert mixed.knowledge.views[0].status == "failed"
    assert (
        target.knowledge.views[0].status == later.knowledge.views[0].status == "failed"
    )


@pytest.mark.asyncio
async def test_removed_revision_boundary_uses_default_history(cast, monkeypatch):
    scene, _ = cast
    editor = get_agent("editor")
    analyze = AsyncMock()
    monkeypatch.setattr(get_agent("summarizer"), "analyze_perceptions", analyze)
    with RevisionContext(999999):
        assert READER.split(": ", 1)[1] in "\n".join(
            editor.revision_context_history(scene.character_data["Bob"], budget=1024)
        )
    analyze.assert_not_awaited()


def test_bind_keeps_legacy_bucket_rule_in_perception_mode(cast):
    from talemate.agents.summarize.context_history import ContextHistoryParams

    scene, _ = cast
    params = ContextHistoryParams(perspective="Bob").bind(scene)
    assert params._knowledge_index is not None


@pytest.mark.asyncio
async def test_retrieval_projects_owned_history(cast, monkeypatch):
    from talemate.agents.memory.rag import MemoryRAGMixin

    scene, mixed = cast
    scene.ts = 10
    mixed.present = ["Alice", "Bob", "Cara"]
    scene.history[1].present = ["Alice"]
    scene.history[2].present = ["Bob"]
    conversation = get_agent("conversation")
    conversation.actions["character_knowledge"].enabled = True
    conversation.actions["character_knowledge"].config[
        "perspective_filter"
    ].value = True
    monkeypatch.setattr(
        "talemate.agents.summarize.context_history.project_character_history",
        Mock(side_effect=AssertionError("Unconverted caller projected history")),
    )
    expected = "sapphire is hidden in her boot"

    request = AsyncMock(return_value=("", {"answer": "none", "items": []}))
    monkeypatch.setattr(Prompt, "request", request)
    memory = get_agent("memory")
    monkeypatch.setattr(
        memory, "audience_character_context", AsyncMock(return_value="")
    )

    async def operation(viewer, callback):
        return await callback(None)

    monkeypatch.setattr(memory, "audience_operation", operation)
    await conversation.memory_pass(scene.character_data["Bob"], [])
    history = "".join(request.call_args.kwargs["vars"]["scene_history"])
    assert expected not in history and "Bob was away" not in history

    monkeypatch.setattr(conversation, "semantic_context", AsyncMock(return_value=[]))
    extract = AsyncMock(return_value="")
    monkeypatch.setattr(
        get_agent("world_state"), "analyze_text_and_extract_context", extract
    )
    await MemoryRAGMixin.rag_build(
        conversation,
        character=scene.character_data["Bob"],
        retrieval_method="questions",
    )
    assert expected not in extract.call_args.args[0]
    assert "Bob was away" not in extract.call_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_in_prefix", [False, True])
async def test_queued_revision_only_shares_cancellation_from_its_prefix(
    cast, monkeypatch, failure_in_prefix
):
    import asyncio

    scene, mixed = cast
    summarizer = get_agent("summarizer")
    target = CharacterMessage(message="Bob: Revision target.")
    later = NarratorMessage(message="Later passage.")
    scene.history.extend([target, later])
    failed = mixed if failure_in_prefix else later
    failed.present = ["Bob"]
    set_source_perspectives(
        scene, "message", failed.id, [{"audience": ["Bob"], "status": "failed"}]
    )
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def analyze(scene, message):
        calls.append(message.id)
        entered.set()
        await release.wait()
        raise GenerationCancelled("Cancelled source analysis")

    monkeypatch.setattr(summarizer, "analyze_perceptions", analyze)
    whole_scene = asyncio.create_task(summarizer.ensure_perceptions(scene))
    await entered.wait()
    prefix = asyncio.create_task(
        summarizer.ensure_perceptions(scene, before_message_id=target.id)
    )
    await asyncio.sleep(0)
    release.set()
    with pytest.raises(GenerationCancelled, match="Cancelled source"):
        await whole_scene
    if failure_in_prefix:
        with pytest.raises(GenerationCancelled, match="Prerequisite"):
            await prefix
    else:
        await prefix
    assert calls == [failed.id]


@pytest.mark.parametrize("format", ["movie_script", "ai_aware", "chat", "narrative"])
def test_colonless_reader_message_cannot_become_speaker_header(
    cast, monkeypatch, format
):
    scene, mixed = cast
    monkeypatch.setattr(
        type(scene), "conversation_format", property(lambda self: format)
    )
    scene.edit_message(mixed.id, "Alice walks in and says the vault code is 4417.")
    set_source_perspectives(
        scene,
        "message",
        mixed.id,
        [{"audience": ["Bob"], "status": "ready", "text": "Someone walks in."}],
    )
    original = mixed.model_dump()
    text = "".join(project_character_history(scene, "Bob"))
    assert text.strip() == "Someone walks in."
    assert "4417" not in text
    assert mixed.model_dump() == original


@pytest.mark.asyncio
@pytest.mark.parametrize("already_failed", [False, True])
async def test_later_failure_cannot_mask_prefix_cancellation(
    cast, monkeypatch, already_failed
):
    import asyncio

    scene, mixed = cast
    summarizer = get_agent("summarizer")
    target = CharacterMessage(message="Bob: Revision target.")
    later = NarratorMessage(message="Later passage.")
    scene.history.extend([target, later])
    set_source_perspectives(
        scene, "message", mixed.id, [{"audience": ["Bob"], "status": "failed"}]
    )
    failures = summarizer._perception_failures.setdefault(scene, {})
    if already_failed:
        failures[mixed.id] = 1
    lock = summarizer._perception_locks.setdefault(scene, asyncio.Lock())
    analyze = AsyncMock()
    monkeypatch.setattr(summarizer, "analyze_perceptions", analyze)
    async with lock:
        waiter = asyncio.create_task(
            summarizer.ensure_perceptions(scene, before_message_id=target.id)
        )
        await asyncio.sleep(0)
        failures[mixed.id] = failures.get(mixed.id, 0) + 1
        failures[later.id] = failures.get(later.id, 0) + 1
    with pytest.raises(GenerationCancelled, match="Prerequisite"):
        await waiter
    analyze.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "template",
    [
        "revision-rewrite",
        "unslop",
        "unslop-narration",
        "unslop-summarization",
        "unslop-contextual-generation",
    ],
)
async def test_revision_templates_never_render_matched_reader_text(cast, template):
    scene, _ = cast
    editor = get_agent("editor")
    private_match = "MATCHED-READER-SECRET-4417"
    vars = {
        "scene": scene,
        "character": scene.character_data["Bob"],
        "text": "CANDIDATE-LINE-TO-REVISE",
        "repetition": [
            {
                "text_a": "CANDIDATE-LINE-TO-REVISE",
                "text_b": private_match,
                "similarity": 100,
            }
        ],
        "bad_prose": [],
        "repetition_handling": "rewrite",
        "dynamic_instructions": [],
        "max_tokens": 10000,
        "response_length": 128,
        "revision_context_history": editor.revision_context_history,
        "scene_analysis": "",
        "summarization_history": [PUBLIC],
        "context_type": "character detail",
        "context_name": "Bob",
    }
    with ActiveAgent(editor, editor.revision_unslop):
        rendered = Prompt.get("editor." + template, vars=vars).render()
    assert "CANDIDATE-LINE-TO-REVISE" in rendered
    assert private_match not in rendered
