import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from _decision_test_helpers import FakeDecisionProvider
from conftest import MockScene, bootstrap_scene
from talemate.context import ActiveScene
from talemate.decisions import DecisionService, ProviderCapabilities, ProviderResponse
from talemate.prompts.base import PrependTemplateDirectories
from talemate.world_state.templates.decision_checks import (
    default_writing_style_decision_checks,
)
from talemate.scene_message import NarratorMessage


class EditorScene(MockScene):
    @property
    def writing_style(self):
        return self.test_writing_style


class Provider(FakeDecisionProvider):
    def __init__(self, probabilities):
        super().__init__()
        self.probabilities = probabilities

    def respond(self, request):
        return ProviderResponse(
            answers={
                key: {"type": "noul", "p_true": self.probabilities.get(key, 0.1)}
                for key in request.questions
            },
            response_body={},
        )


@pytest.fixture
def editor_case(monkeypatch):
    from talemate.agents.editor import decision_checks
    from talemate.world_state.templates.content import WritingStyle, PhraseDetection

    data = json.loads(
        (Path(__file__).parent / "data/editor_decisions/platform.json").read_text()
    )
    scene = EditorScene()
    scene.active = True
    scene.test_writing_style = WritingStyle(
        name="Plain",
        decision_checks=default_writing_style_decision_checks(),
        instructions=data["style"],
        phrases=[PhraseDetection(**data["rule"])],
    )
    agents = bootstrap_scene(scene)
    editor = agents["editor"]
    editor.actions["revision"].enabled = True
    editor.actions["revision"].config["revision_method"].value = "rewrite"
    editor.actions["revision"].config["decision_checks"].value = True
    previous = NarratorMessage(data["previous"])
    current = NarratorMessage(data["current"])
    scene.history = [previous, current]
    provider = Provider(data["probabilities"])
    service = DecisionService(provider, enabled=True, timeout_seconds=1.5)
    monkeypatch.setattr(decision_checks, "decision_service", service)
    monkeypatch.setattr(
        editor, "_revision_evaluate_semantic_similarity", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        editor,
        "revision_detect_bad_prose",
        AsyncMock(
            return_value=[
                {
                    **data["rule"],
                    "reason": "fixture rule",
                    "matched": data["rule"]["phrase"],
                }
            ]
        ),
    )
    monkeypatch.setattr(editor, "rag_build", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        agents["summarizer"], "get_cached_analysis", AsyncMock(return_value="")
    )
    monkeypatch.setattr(
        agents["director"], "get_cached_character_guidance", AsyncMock(return_value="")
    )
    client = editor.client
    monkeypatch.setattr(
        client,
        "send_prompt",
        AsyncMock(
            return_value=f"<REVISION>{data['revised']}</REVISION><FIX>{data['revised']}</FIX>"
        ),
    )
    monkeypatch.setattr(editor, "emit_message", AsyncMock())
    with ActiveScene(scene):
        yield SimpleNamespace(
            scene=scene,
            editor=editor,
            current=current,
            previous=previous,
            provider=provider,
            service=service,
            client=client,
            data=data,
        )


async def revise(case):
    from talemate.agents.editor.revision import RevisionContext, RevisionInformation

    info = RevisionInformation(text=case.current.message)
    with RevisionContext(case.current.id):
        result = await case.editor.revision_revise(info)
    return result, info


@pytest.mark.parametrize("method", ["rewrite", "unslop"])
@pytest.mark.parametrize("mode", ["off", "on", "timeout"])
async def test_controlled_comparison(editor_case, method, mode):
    c = editor_case
    c.editor.actions["revision"].config["revision_method"].value = method
    c.editor.actions["revision"].config["decision_checks"].value = mode != "off"
    if mode == "timeout":
        c.service.timeout_seconds = 0.01
        c.provider.handler = lambda request: asyncio.Event().wait()
    result, _ = await asyncio.wait_for(revise(c), 3)
    assert result == c.data["revised"]
    c.client.send_prompt.assert_awaited_once()
    prompt = str(c.client.send_prompt.call_args.args[0])
    assert c.data["current"] in prompt
    if mode == "on":
        c.editor._revision_evaluate_semantic_similarity.assert_not_awaited()
        c.editor.revision_detect_bad_prose.assert_not_awaited()
        record = next(iter(c.service.log.records.values()))
        assert [
            (f["passage_id"], f["kind"])
            for f in record.actions[0].arguments["decision_findings"]
        ] == [("s1", "repetition"), ("s2", "style")]
        assert "s1 / repetition" in prompt and "s2 / style" in prompt
        assert record.state["history"] == [c.data["previous"]]
        assert record.state["text"] == c.data["current"]
        assert record.actions[0].status == "completed"
        assert (
            record.actions[0].elapsed_ms is not None and record.elapsed_ms is not None
        )
    else:
        c.editor._revision_evaluate_semantic_similarity.assert_awaited_once()
        c.editor.revision_detect_bad_prose.assert_awaited_once()
        assert "DECISION FINDINGS" not in prompt
        assert c.data["rule"]["instructions"] in prompt
        if mode == "off":
            assert not c.provider.calls and not c.service.log.records
        else:
            record = next(iter(c.service.log.records.values()))
            assert record.failure.code == "timeout"
            assert record.actions[0].action == "disabled_path"
            assert record.actions[0].status == "completed"


@pytest.mark.parametrize("method", ["rewrite", "unslop"])
@pytest.mark.parametrize(
    "minimum,probabilities,reason",
    [
        (1, {}, "below_thresholds"),
        (1, {"s1_description_reuse": 0.79}, "below_thresholds"),
        (2, {"s1_repetition": 0.93, "s1_style": 0.91}, "below_minimum"),
        (
            2,
            {"s1_repetition": 0.93, "s1_description_reuse": 0.95},
            "below_minimum",
        ),
    ],
)
async def test_negative_and_distinct_passage_gate(
    editor_case, method, minimum, probabilities, reason
):
    c = editor_case
    c.editor.actions["revision"].config["revision_method"].value = method
    c.editor.actions["revision"].config["min_issues"].value = minimum
    c.provider.probabilities = probabilities
    result, _ = await revise(c)
    assert result == c.data["current"]
    c.client.send_prompt.assert_not_awaited()
    c.editor._revision_evaluate_semantic_similarity.assert_not_awaited()
    c.editor.revision_detect_bad_prose.assert_not_awaited()
    assert next(iter(c.service.log.records.values())).outcomes[0]["reason"] == reason


@pytest.mark.parametrize("method", ["rewrite", "unslop"])
@pytest.mark.parametrize("handling", ["remove", "rewrite"])
async def test_description_reuse_preserves_event(editor_case, method, handling):
    c = editor_case
    c.editor.actions["revision"].config["revision_method"].value = method
    c.editor.actions["revision"].config["repetition_handling"].value = handling
    c.provider.probabilities = {"s1_description_reuse": 0.8}

    assert (await revise(c))[0] == c.data["revised"]

    assert len(c.provider.calls) == 1
    c.client.send_prompt.assert_awaited_once()
    c.editor._revision_evaluate_semantic_similarity.assert_not_awaited()
    c.editor.revision_detect_bad_prose.assert_not_awaited()
    record = next(iter(c.service.log.records.values()))
    assert len(record.actions) == 1
    findings = record.actions[0].arguments["decision_findings"]
    assert len(findings) == 1
    finding = findings[0]
    assert (finding["passage_id"], finding["kind"], finding["p_true"]) == (
        "s1",
        "repetition",
        0.8,
    )
    assert finding["text"] == c.provider.calls[0].state["passages"][0]["text"]
    assert "Replace the reused description" in finding["instructions"]
    assert "Preserve the event and factual content" in finding["instructions"]
    prompt = str(c.client.send_prompt.call_args.args[0])
    assert finding["instructions"] in prompt
    assert "For repetition," not in prompt
    assert "For a description-reuse finding" in prompt
    if method == "rewrite":
        assert "**For each flagged item, pick one:**" not in prompt


@pytest.mark.parametrize("method", ["rewrite", "unslop"])
async def test_all_findings_share_one_batch_and_revision(editor_case, method):
    c = editor_case
    c.editor.actions["revision"].config["revision_method"].value = method
    c.editor.actions["revision"].config["min_issues"].value = 2
    c.provider.probabilities["s1_description_reuse"] = 0.95

    assert (await revise(c))[0] == c.data["revised"]

    assert len(c.provider.calls) == 1
    request = c.provider.calls[0]
    assert set(request.questions) == {
        f"s{i}_{kind}"
        for i in (1, 2)
        for kind in ("repetition", "description_reuse", "style")
    }
    c.client.send_prompt.assert_awaited_once()
    record = next(iter(c.service.log.records.values()))
    assert len(record.actions) == 1
    findings = record.actions[0].arguments["decision_findings"]
    assert [(f["passage_id"], f["kind"]) for f in findings] == [
        ("s1", "repetition"),
        ("s1", "repetition"),
        ("s2", "style"),
    ]
    prompt = str(c.client.send_prompt.call_args.args[0])
    assert all(
        " ".join(f["instructions"].split()) in " ".join(prompt.split())
        for f in findings
    )
    assert "F1 (s1 / repetition)" in prompt
    assert "F2 (s1 / repetition)" in prompt
    assert "F3 (s2 / style)" in prompt
    if method == "rewrite":
        assert "`F1`, `F2`, etc. from DECISION FINDINGS" in prompt
        assert "referenced by its label (`REPEATED 1`" not in prompt


@pytest.mark.parametrize(
    "target", ["rewrite", "narration", "character", "context", "summary"]
)
async def test_style_evidence_is_rendered_once(editor_case, target):
    from talemate.agents.editor.revision import RevisionContext, RevisionInformation
    from talemate.character import Character

    c = editor_case
    c.editor.actions["revision"].config["revision_method"].value = (
        "rewrite" if target == "rewrite" else "unslop"
    )
    c.provider.probabilities = {"s1_style": 0.9, "s2_style": 0.95}
    info = RevisionInformation(text=c.data["current"])
    if target == "character":
        info.character = Character(name="Mara")
    elif target == "context":
        info.context_type = "world context"
        info.context_name = "Platform"
    elif target == "summary":
        info.summarization_history = ["Source facts."]
    with RevisionContext(c.current.id):
        await c.editor.revision_revise(info)

    c.client.send_prompt.assert_awaited_once()
    prompt = str(c.client.send_prompt.call_args.args[0])
    assert prompt.count(c.data["style"]) == 1
    assert prompt.count(c.data["rule"]["instructions"]) == 1
    record = next(iter(c.service.log.records.values()))
    for finding in record.actions[0].arguments["decision_findings"]:
        assert c.data["style"] not in finding["instructions"]
        assert c.data["rule"]["instructions"] not in finding["instructions"]


async def test_style_evidence_reserves_rewrite_context_budget(editor_case, monkeypatch):
    from unittest.mock import Mock

    c = editor_case
    history = Mock(return_value=[])
    monkeypatch.setattr(c.editor, "revision_context_history", history)
    await revise(c)
    initial_budget = history.call_args.kwargs["budget"]
    c.scene.test_writing_style.instructions += " Use concrete sensory details." * 100
    await revise(c)
    assert history.call_args.kwargs["budget"] < initial_budget - 100


async def test_repeated_beats_toggle_omits_both_repetition_questions(editor_case):
    c = editor_case
    c.scene.test_writing_style.decision_checks[0].active = False
    await revise(c)
    assert set(c.provider.calls[0].questions) == {"s1_style", "s2_style"}
    record = next(iter(c.service.log.records.values()))
    assert [f["kind"] for f in record.actions[0].arguments["decision_findings"]] == [
        "style"
    ]


@pytest.mark.parametrize(
    "failure", ["missing", "unavailable", "disabled", "oversize", "template", "result"]
)
async def test_before_dispatch_failures_fall_back_once(editor_case, failure, tmp_path):
    c = editor_case
    if failure == "missing":
        c.provider.handler = AsyncMock(
            return_value=ProviderResponse(answers={}, response_body={})
        )
    elif failure == "unavailable":
        c.provider.ready = False
    elif failure == "disabled":
        c.service.enabled = False
    elif failure == "oversize":
        c.provider.capabilities = ProviderCapabilities(max_input_tokens=1)
    source = {
        "template": "{{ undefined_value }}",
        "result": "{{ decision_result(12) }}",
    }.get(failure)
    if source:
        (tmp_path / "decision-checks.jinja2").write_text(source)
    with PrependTemplateDirectories(str(tmp_path)):
        result, _ = await revise(c)
    assert result == c.data["revised"]
    c.client.send_prompt.assert_awaited_once()
    c.editor.revision_detect_bad_prose.assert_awaited_once()
    records = list(c.service.log.records.values())
    assert records[-1].status == "failed"
    assert records[-1].actions[0].action == "disabled_path"
    assert records[-1].actions[0].status == "completed"


OVERRIDE = """{% set r = decide("custom", state=info.text, questions={"custom": {"type": "noul", "instructions": "Custom question?"}}) %}
{% set findings = [{"passage_id": "s2", "text": "A shiver ran down her spine.", "kind": "style", "instructions": "Use a concrete action."}] %}
{% set value = agent_action("editor", "revision_rewrite", info=info, decision_findings=findings, _decision=r) %}
"""


@pytest.mark.parametrize(
    "ending",
    [
        "{{ decision_result(value) }}",
        "{{ undefined_value }}",
        "{{ decision_result(12) }}",
        '{{ decision_result(agent_action("editor", "revision_rewrite", info=info, decision_findings=findings, _decision=r)) }}',
    ],
)
async def test_override_and_failures_after_start_never_dispatch_twice(
    editor_case, tmp_path, ending
):
    c = editor_case
    c.editor.actions["revision"].config["min_issues"].value = 10
    (tmp_path / "decision-checks.jinja2").write_text(OVERRIDE + ending)
    with PrependTemplateDirectories(str(tmp_path)):
        result, _ = await revise(c)
    c.client.send_prompt.assert_awaited_once()
    c.editor.revision_detect_bad_prose.assert_not_awaited()
    assert result == (
        c.data["revised"]
        if ending == "{{ decision_result(value) }}"
        else c.data["current"]
    )
    assert c.provider.calls[0].questions["custom"].instructions == "Custom question?"
    assert all(
        a.action != "disabled_path"
        for r in c.service.log.records.values()
        for a in r.actions
    )


@pytest.mark.parametrize("method", ["rewrite", "unslop"])
async def test_override_can_choose_action_with_empty_findings(
    editor_case, tmp_path, method
):
    c = editor_case
    c.editor.actions["revision"].config["revision_method"].value = method
    c.editor.actions["revision"].config["min_issues"].value = 10
    source = OVERRIDE.replace("decision_findings=findings", "decision_findings=[]")
    source = source.replace('"revision_rewrite"', f'"revision_{method}"')
    (tmp_path / "decision-checks.jinja2").write_text(
        source + "{{ decision_result(value) }}"
    )
    with PrependTemplateDirectories(str(tmp_path)):
        assert (await revise(c))[0] == c.data["revised"]
    c.client.send_prompt.assert_awaited_once()
    c.editor.revision_detect_bad_prose.assert_not_awaited()
    c.editor._revision_evaluate_semantic_similarity.assert_not_awaited()
    record = next(iter(c.service.log.records.values()))
    assert len(record.actions) == 1
    assert record.actions[0].arguments["decision_findings"] == []


@pytest.mark.parametrize(
    "change",
    [
        "cancel",
        "release",
        "version",
        "edit",
        "remove",
        "disable",
        "style_swap",
        "style_edit",
        "style_remove",
    ],
)
@pytest.mark.parametrize("phase", ["decision", "rewrite"])
async def test_input_invalidation_cancels_without_fallback(editor_case, change, phase):
    c = editor_case

    async def invalidate(*args, **kwargs):
        if change == "cancel":
            c.scene.cancel_requested = True
        elif change == "release":
            c.scene.active = False
        elif change == "version":
            c.current.append_version(c.current.message, source="custom")
        elif change == "edit":
            c.current.message = "A newer edit."
        elif change == "disable":
            c.editor.actions["revision"].enabled = False
        elif change == "style_remove":
            c.scene.test_writing_style = None
        elif change in ("style_swap", "style_edit"):
            c.scene.test_writing_style = c.scene.test_writing_style.model_copy(
                deep=True,
                update={"uid": "different-style"} if change == "style_swap" else {},
            )
        else:
            c.scene.history.remove(c.current)
        await asyncio.sleep(0)
        if phase == "decision":
            return ProviderResponse(answers={}, response_body={})
        return f"<REVISION>{c.data['revised']}</REVISION>"

    if phase == "decision":
        c.provider.handler = invalidate
    else:
        c.client.send_prompt.side_effect = invalidate
    result, info = await revise(c)
    assert result == c.data["current"]
    assert info.skip_reason == "cancelled"
    assert c.client.send_prompt.await_count == (phase == "rewrite")
    c.editor.revision_detect_bad_prose.assert_not_awaited()
    assert all(
        a.action != "disabled_path"
        for r in c.service.log.records.values()
        for a in r.actions
    )


@pytest.mark.parametrize("enabled", [False, True])
async def test_revision_decision_toggle_is_the_only_agent_check_setting(
    editor_case, enabled
):
    from talemate.agents.editor import EditorAgent

    editor = editor_case.editor
    await editor.apply_config(
        actions={
            "revision": {
                "enabled": True,
                "config": {"decision_checks": {"value": enabled}},
            }
        }
    )
    actions = EditorAgent.config_options(agent=editor)["actions"]
    assert "decision_checks" not in actions
    assert actions["revision"]["config"]["decision_checks"]["value"] is enabled
    assert editor.decision_checks_enabled is enabled
    assert "threshold" not in actions["revision"]["config"]


async def test_default_off_and_dedupe_unchanged(editor_case):
    from talemate.agents.editor import EditorAgent

    c = editor_case
    assert not EditorAgent.init_actions()["revision"].config["decision_checks"].value
    assert EditorAgent.init_actions()["revision"].config["repetition_range"].value == 15
    c.editor.actions["revision"].config["revision_method"].value = "dedupe"
    await revise(c)
    assert not c.provider.calls
    c.client.send_prompt.assert_not_awaited()


@pytest.mark.parametrize(
    "blocked", ["revision", "automatic", "target", "player", "context"]
)
async def test_checks_do_not_expand_automatic_eligibility(editor_case, blocked):
    from talemate.agents.editor.revision import RevisionDisabled

    c = editor_case
    if blocked == "revision":
        c.editor.actions["revision"].enabled = False
    elif blocked == "automatic":
        c.editor.actions["revision"].config["automatic_revision"].value = False
    elif blocked == "target":
        c.editor.actions["revision"].config["automatic_revision_targets"].value = []
    elif blocked == "player":
        c.current.source = "player"
    if blocked == "context":
        with RevisionDisabled():
            assert not await c.editor.maybe_revise_inplace(c.current)
    else:
        assert not await c.editor.maybe_revise_inplace(c.current)
    assert not c.provider.calls
    c.client.send_prompt.assert_not_awaited()


@pytest.mark.parametrize("checks", [False, True])
@pytest.mark.parametrize("entry", ["manual", "push"])
async def test_entry_points_apply_one_version(editor_case, checks, entry, monkeypatch):
    from talemate.agents.editor.websocket_handler import EditorWebsocketHandler
    from talemate.events import HistoryEvent

    c = editor_case
    c.editor.actions["revision"].config["decision_checks"].value = checks
    if entry == "manual":
        c.editor.actions["revision"].config["automatic_revision"].value = False
        handler = EditorWebsocketHandler(SimpleNamespace(scene=c.scene))
        monkeypatch.setattr(handler, "signal_operation_done", AsyncMock())
        await handler.handle_request_revision.__wrapped__(
            handler, {"message_id": c.current.id}
        )
        handler.signal_operation_done.assert_awaited_once()
    else:
        await c.editor.revision_on_push(
            HistoryEvent(event_type="push_history", scene=c.scene, messages=[c.current])
        )
    assert c.current.message == c.data["revised"]
    assert len(c.current.versions) == 2
    assert c.current.versions[0].message == c.data["current"]
    assert c.current.versions[-1].source == "revision"
    assert len(c.provider.calls) == int(checks)
    c.client.send_prompt.assert_awaited_once()


@pytest.mark.parametrize("checks", [False, True])
@pytest.mark.parametrize("target", ["contextual_generation", "summarization"])
async def test_generated_content_context_and_selection(editor_case, checks, target):
    from talemate.agents.creator.assistant import (
        ContentGenerationContext,
        ContextualGenerateEmission,
    )
    from talemate.agents.summarize import SummarizeEmission
    from talemate.world_state.templates.content import (
        GenerationOptions,
        WritingStyle,
        PhraseDetection,
    )

    c = editor_case
    c.editor.actions["revision"].config["decision_checks"].value = checks
    c.editor.actions["revision"].config["revision_method"].value = "unslop"
    c.editor.actions["revision"].config["automatic_revision_targets"].value = [target]
    if target == "summarization":
        emission = SummarizeEmission(
            agent=c.editor,
            response=c.data["current"],
            summarization_history=["Full source history."],
        )
    else:
        emission = ContextualGenerateEmission(
            agent=c.editor,
            response=c.data["current"],
            content_generation_context=ContentGenerationContext(
                context="world context:Platform",
                instructions="Describe the station.",
                information="Source facts.",
                original="Old platform description.",
                generation_options=GenerationOptions(
                    writing_style=WritingStyle(
                        name="Generation only",
                        instructions="Use an unrelated generation style.",
                        phrases=[
                            PhraseDetection(
                                phrase="generation-only phrase",
                                instructions="Generation-only correction.",
                            )
                        ],
                    )
                ),
            ),
        )
    await c.editor.revision_on_generation(emission)
    assert emission.response == c.data["revised"]
    c.client.send_prompt.assert_awaited_once()
    assert len(c.provider.calls) == int(checks)
    if checks:
        state = c.provider.calls[0].state
        if target == "summarization":
            assert state["history"] == []
            assert state["summarization_history"] == ["Full source history."]
        else:
            assert state["source_context"]["information"] == "Source facts."
            assert state["source_context"]["instructions"] == "Describe the station."
            assert state["context_name"] == "Platform"
            assert state["writing_style"] == c.data["style"]
            assert [r["instructions"] for r in state["prose_rules"]] == [
                c.data["rule"]["instructions"]
            ]
        assert "s1 / repetition" in str(c.client.send_prompt.call_args.args[0])
        assert "s2 / style" in str(c.client.send_prompt.call_args.args[0])
    prompt = str(c.client.send_prompt.call_args.args[0])
    assert "Use an unrelated generation style." not in prompt
    assert c.data["style"] in prompt


async def test_manual_stale_input_is_not_applied(editor_case, monkeypatch):
    from talemate.agents.editor.websocket_handler import EditorWebsocketHandler

    c = editor_case

    async def changed(*args, **kwargs):
        c.current.message = "Newer user edit."
        return f"<REVISION>{c.data['revised']}</REVISION>"

    c.client.send_prompt.side_effect = changed
    handler = EditorWebsocketHandler(SimpleNamespace(scene=c.scene))
    monkeypatch.setattr(handler, "signal_operation_done", AsyncMock())
    await handler.handle_request_revision.__wrapped__(
        handler, {"message_id": c.current.id}
    )
    assert c.current.message == "Newer user edit."
    assert len(c.current.versions) == 1
    handler.signal_operation_done.assert_awaited_once()


async def test_owner_task_cancellation_stops_request(editor_case):
    c = editor_case
    started = asyncio.Event()
    stopped = asyncio.Event()

    async def wait(request):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    c.provider.handler = wait
    task = asyncio.create_task(revise(c))
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    await asyncio.wait_for(stopped.wait(), 1)
    c.client.send_prompt.assert_not_awaited()
    c.editor.revision_detect_bad_prose.assert_not_awaited()


@pytest.mark.parametrize("method", ["rewrite", "unslop"])
@pytest.mark.parametrize(
    "response,reason",
    [("No marked result.", "no_revision"), ("oversize", "too_long"), ("error", None)],
)
async def test_revision_failure_preserves_original_without_fallback(
    editor_case, method, response, reason
):
    c = editor_case
    c.editor.actions["revision"].config["revision_method"].value = method
    if response == "error":
        c.client.send_prompt.side_effect = RuntimeError("fixture dispatch failure")
    else:
        c.client.send_prompt.return_value = (
            response
            if response != "oversize"
            else "<REVISION>"
            + c.data["current"] * 5
            + "</REVISION><FIX>"
            + c.data["current"] * 5
            + "</FIX>"
        )
    result, info = await revise(c)
    assert result == c.data["current"]
    assert info.skip_reason == reason
    c.client.send_prompt.assert_awaited_once()
    c.editor.revision_detect_bad_prose.assert_not_awaited()


@pytest.mark.parametrize("history_range", [1, 3, 15])
async def test_history_window_without_style_instructions(editor_case, history_range):
    from talemate.scene_message import DirectorMessage

    c = editor_case
    c.scene.test_writing_style.instructions = None
    c.scene.test_writing_style.phrases = []
    c.editor.actions["revision"].config["repetition_range"].value = history_range
    c.scene.history = [NarratorMessage(f"Earlier message {i}.") for i in range(5)] + [
        DirectorMessage("Not story context."),
        c.current,
        NarratorMessage("Future message."),
    ]
    c.provider.probabilities = {}
    await revise(c)
    request = c.provider.calls[0]
    expected = [f"Earlier message {i}." for i in range(5)][-history_range:]
    assert request.state["history"] == expected
    from talemate.agents.editor.revision import RevisionContext

    with RevisionContext(c.current.id):
        assert c.editor.revision_repetition_history() == list(reversed(expected))
    assert set(request.questions) == {
        "s1_repetition",
        "s1_description_reuse",
        "s2_repetition",
        "s2_description_reuse",
    }
    assert request.state["text"] == c.data["current"]


async def test_character_prefix_is_preserved(editor_case):
    from talemate.agents.editor.revision import RevisionContext, RevisionInformation
    from talemate.character import Character
    from talemate.scene_message import CharacterMessage

    c = editor_case
    character = Character(name="Mara")
    message = CharacterMessage("Mara: " + c.data["current"])
    c.scene.history[-1] = message
    with RevisionContext(message.id):
        result = await c.editor.revision_revise(
            RevisionInformation(text=message.message, character=character)
        )
    assert result == "Mara: " + c.data["revised"]
    assert c.provider.calls[0].state["text"] == message.message
    assert (
        c.provider.calls[0].state["passages"][0]["text"]
        == "She scanned the empty platform once more."
    )


async def test_exact_threshold_and_template_override_comparison(editor_case, tmp_path):
    c = editor_case
    c.provider.probabilities = {"s1_repetition": 0.8}
    assert (await revise(c))[0] == c.data["revised"]
    record = next(reversed(c.service.log.records.values()))
    assert record.outcomes[0]["details"]["flagged_question_ids"] == ["s1_repetition"]
    c.client.send_prompt.reset_mock()
    source = (
        Path(__file__).parent.parent
        / "src/talemate/prompts/templates/editor/decision-checks.jinja2"
    ).read_text()
    (tmp_path / "decision-checks.jinja2").write_text(
        source.replace(
            "probability >= evaluation.threshold", "probability > evaluation.threshold"
        )
    )
    with PrependTemplateDirectories(str(tmp_path)):
        assert (await revise(c))[0] == c.data["current"]
    record = next(reversed(c.service.log.records.values()))
    assert record.outcomes[0]["details"]["flagged_question_ids"] == []
    c.client.send_prompt.assert_not_awaited()


@pytest.mark.parametrize("method", ["rewrite", "unslop"])
@pytest.mark.parametrize(
    "no_questions", ["all_inactive", "no_style", "empty", "inapplicable"]
)
async def test_no_applicable_checks_use_ordinary_revision(
    editor_case, method, no_questions
):
    c = editor_case
    c.editor.actions["revision"].config["revision_method"].value = method
    if no_questions == "no_style":
        c.scene.test_writing_style = None
    elif no_questions == "empty":
        c.scene.test_writing_style.decision_checks = []
    elif no_questions == "inapplicable":
        c.scene.test_writing_style.decision_checks = [
            c.scene.test_writing_style.decision_checks[1]
        ]
        c.scene.test_writing_style.instructions = None
        c.scene.test_writing_style.phrases = []
    else:
        for check in c.scene.test_writing_style.decision_checks:
            check.active = False
    result, _ = await revise(c)
    assert not c.provider.calls
    assert not c.service.log.records
    c.editor._revision_evaluate_semantic_similarity.assert_awaited_once()
    decision_path_calls = c.client.send_prompt.await_count
    prose_calls = c.editor.revision_detect_bad_prose.await_count
    c.client.send_prompt.reset_mock()
    c.editor.revision_detect_bad_prose.reset_mock()
    c.editor.actions["revision"].config["decision_checks"].value = False
    assert (await revise(c))[0] == result
    assert c.client.send_prompt.await_count == decision_path_calls
    assert c.editor.revision_detect_bad_prose.await_count == prose_calls


@pytest.mark.parametrize("method", ["rewrite", "unslop"])
async def test_check_thresholds_and_custom_routing_are_independent(editor_case, method):
    from talemate.world_state.templates.decision_checks import DecisionCheck

    c = editor_case
    c.editor.actions["revision"].config["revision_method"].value = method
    c.scene.test_writing_style.decision_checks[0].threshold = 0.95
    c.scene.test_writing_style.decision_checks[1].threshold = 0.90
    c.scene.test_writing_style.decision_checks.append(
        DecisionCheck(
            name="Concrete images",
            threshold=0.55,
            questions=[
                {
                    "id": "concrete",
                    "question": "Is {passage_id} too abstract? Literal JSON: {example}",
                    "true_criteria": "An abstraction in {passage_id}.",
                    "false_criteria": "A concrete image.",
                    "kind": "style",
                    "instructions": "Use one specific physical detail.",
                }
            ],
        )
    )
    c.provider.probabilities = {
        "s1_repetition": 0.94,
        "s1_description_reuse": 0.94,
        "s1_style": 0.89,
        "s2_concrete": 0.55,
    }
    assert (await revise(c))[0] == c.data["revised"]
    (request,) = c.provider.calls
    assert (
        request.questions["s2_concrete"].instructions
        == "Is s2 too abstract? Literal JSON: {example}"
    )
    assert request.questions["s2_concrete"].true_criteria == "An abstraction in s2."
    record = next(iter(c.service.log.records.values()))
    (finding,) = record.actions[0].arguments["decision_findings"]
    assert finding["passage_id"] == "s2"
    assert finding["instructions"] == "Use one specific physical detail."
    assert finding["kind"] == "style"
    c.client.send_prompt.assert_awaited_once()
    c.editor.revision_detect_bad_prose.assert_not_awaited()


async def test_negative_log_records_each_compared_threshold(editor_case):
    c = editor_case
    c.provider.probabilities = {}
    c.scene.test_writing_style.decision_checks[0].threshold = 0.91
    c.scene.test_writing_style.decision_checks[1].threshold = 0.76
    await revise(c)
    record = next(iter(c.service.log.records.values()))
    assert record.outcomes[0]["details"]["thresholds"] == {
        f"s{i}_{question}": threshold
        for i in (1, 2)
        for question, threshold in (
            ("repetition", 0.91),
            ("description_reuse", 0.91),
            ("style", 0.76),
        )
    }


@pytest.mark.parametrize("minimum", [1, 2])
async def test_log_presentation_uses_exact_check_passage_and_threshold(
    editor_case, minimum
):
    c = editor_case
    c.editor.actions["revision"].config["min_issues"].value = minimum
    checks = c.scene.test_writing_style.decision_checks
    checks[0].threshold = 0.91
    checks[1].threshold = 0.76
    c.provider.probabilities = {"s1_repetition": 0.91, "s2_style": 0.7599999}
    await revise(c)
    record = next(iter(c.service.log.records.values()))
    assert record.presentation.keys() == record.questions.keys()
    assert record.outcomes[0]["details"]["flagged_question_ids"] == ["s1_repetition"]
    for passage in record.state["passages"]:
        for check in checks:
            for question in check.questions:
                item = record.presentation[f"{passage['id']}_{question.id}"]
                assert item.passage_id == passage["id"]
                assert item.passage_text == passage["text"]
                assert item.group_id == question.id
                assert item.label == check.name
                assert item.instructions == question.question.replace(
                    "{passage_id}", "shown below"
                )
                assert item.threshold == check.threshold
    if minimum == 1:
        assert [
            (finding["passage_id"], finding["p_true"])
            for finding in record.actions[0].arguments["decision_findings"]
        ] == [("s1", 0.91)]
    else:
        assert not record.actions
        assert record.outcomes[0]["reason"] == "below_minimum"
    assert "presentation" not in c.provider.calls[0].model_dump()


@pytest.mark.parametrize(
    "criteria",
    [("", ""), ("Present", ""), ("", "Absent"), (" \n", "\t"), ("Present", "Absent")],
)
async def test_custom_check_optional_criteria_and_passage_binding(
    editor_case, criteria
):
    from talemate.world_state.templates.decision_checks import DecisionCheck

    c = editor_case
    c.scene.test_writing_style.decision_checks.append(
        DecisionCheck(
            name="Concrete action",
            questions=[
                {
                    "id": "concrete",
                    "question": "Does this passage explain a feeling instead of showing an action?",
                    "true_criteria": criteria[0],
                    "false_criteria": criteria[1],
                    "instructions": "Show the feeling through an action.",
                }
            ],
        )
    )
    c.provider.probabilities = {"s2_concrete": 0.9}
    assert (await revise(c))[0] == c.data["revised"]
    (request,) = c.provider.calls
    assert len(request.questions) == 8
    for index in (1, 2):
        question = request.questions[f"s{index}_concrete"]
        assert (
            question.instructions
            == f"Passage s{index}: Does this passage explain a feeling instead of showing an action?"
        )
        has_criteria = all(value.strip() for value in criteria)
        assert question.true_criteria == (criteria[0] if has_criteria else None)
        assert question.false_criteria == (criteria[1] if has_criteria else None)
    record = next(iter(c.service.log.records.values()))
    (finding,) = record.actions[0].arguments["decision_findings"]
    assert finding["passage_id"] == "s2"
    assert finding["text"] == request.state["passages"][1]["text"]
    assert finding["instructions"] == "Show the feeling through an action."
    c.editor._revision_evaluate_semantic_similarity.assert_not_awaited()
    c.client.send_prompt.assert_awaited_once()
