"""Generates the frontend's decision-log fixtures from a real framework run.

The Decision Log view is fed by the websocket route, so its fixtures are the
frames that route sends. Regenerate them with
`TALEMATE_UPDATE_DECISION_FIXTURE=1` and review the diff.
"""

import asyncio
import copy
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from talemate.decisions import (
    DecisionService,
    PolicyAction,
    ProviderResponse,
    decision_service,
)
from talemate.decisions.events import DecisionLog
from talemate.decisions.provider import DecisionError, FailureCode
from talemate.exceptions import GenerationCancelled
from talemate.server.decisions import DecisionsPlugin

FIXTURE = (
    Path(__file__).parents[2]
    / "talemate_frontend/tests/unit/fixtures/decisionLifecycle.json"
)
TEMPLATE = (
    Path(__file__).parents[1] / "data/decisions/editor-repetition.jinja2"
).read_text()
DECIDE = """{% set r = decide("editor-repetition",
    state={"passage": passage, "history": last3},
    questions={"repeats": {
        "type": "noul",
        "instructions": "Does this passage repeat an earlier story beat?"
    }}) %}"""
NO_REASON = (
    DECIDE
    + """
{{ decision_outcome(r, "no_action") }}
{{ decision_result(info.text) }}"""
)
UNASSOCIATED = (
    DECIDE
    + """
{{ agent_action("editor", "revision_rewrite", info=info) }}
{{ decision_result(info.text) }}"""
)
CANCEL_AFTER_ANSWER = (
    DECIDE
    + """
{{ cancel() }}
{{ decision_outcome(r, "no_action", reason="below_threshold", threshold=0.8) }}
{{ decision_result(info.text) }}"""
)
QUESTION_TYPES = """{% set r = decide("editor-style",
    state={"passage": passage},
    questions={
        "repeats": {
            "type": "noul",
            "instructions": "Does this passage repeat an earlier story beat?"
        },
        "tone": {
            "type": "choice",
            "instructions": "Which tone does the passage take?",
            "options": {"warm": "Warm and close", "cool": "Distant and clipped"}
        },
        "tension": {
            "type": "score",
            "instructions": "How much tension does the passage carry?",
            "rubric": ["none", "some", "high"]
        }
    }) %}
{% set threshold = decision_checks[0].threshold %}
{{ decision_outcome(r, "no_action", reason="below_threshold", threshold=threshold) }}
{{ decision_result(info.text) }}"""
TWO_ASKS = (
    DECIDE
    + """
{% set second = decide("editor-style",
    state={"passage": passage},
    questions={"repeats": {
        "type": "noul",
        "instructions": "Does the closing line repeat an earlier one?"
    }}) %}
{{ agent_action("editor", "revision_rewrite", info=info, _decision=r) }}
{{ decision_result(info.text) }}"""
)
NO_REQUEST = """{{ decision_result(info.text) }}"""
BASE_TIME = datetime(2026, 9, 21, 9, 0, tzinfo=timezone.utc)
REQUEST_MS = 140.0
ACTION_MS = 820.0


class Route:
    """The websocket route, so a fixture frame is what the browser receives."""

    def __init__(self, monkeypatch, log):
        monkeypatch.setattr(decision_service, "log", log)
        self.frames = []
        self.plugin = DecisionsPlugin(
            SimpleNamespace(scene=None, queue_put=self.frames.append)
        )

    async def send(self, action):
        await self.plugin.handle({"action": action})


@pytest.fixture
def stage(policy_factory, provider, monkeypatch):
    def start(max_finished=50, enabled=True):
        service = DecisionService(
            provider, enabled=enabled, log=DecisionLog(max_finished=max_finished)
        )
        return service, Route(monkeypatch, service.log)

    def answer(p_true):
        provider.answers = {"repeats": {"type": "noul", "p_true": p_true}}
        provider.raw = {"repeats": {"noul": p_true}}

    return SimpleNamespace(
        create=policy_factory.create,
        editor=policy_factory.editor,
        provider=provider,
        start=start,
        answer=answer,
    )


async def below_threshold(stage):
    """P(repeats)=0.74, 140 ms: below the 0.80 threshold, so no action."""
    stage.answer(0.74)
    service, route = stage.start()
    await stage.create(
        uid="editor.below-threshold", source=TEMPLATE, service=service
    ).run()
    await route.send("snapshot")
    return route.frames


async def per_check_thresholds(stage):
    from talemate.world_state.templates.decision_checks import (
        default_writing_style_decision_checks,
    )

    checks = default_writing_style_decision_checks()
    checks[0].threshold = 0.91
    checks[1].threshold = 0.76

    async def answer(request):
        return ProviderResponse(
            answers={
                key: {"type": "noul", "p_true": 0.74} for key in request.questions
            },
            response_body={},
        )

    stage.provider.handler = answer
    service, route = stage.start()
    source = (
        Path(__file__).parents[2]
        / "src/talemate/prompts/templates/editor/decision-checks.jinja2"
    ).read_text()
    await stage.create(
        uid="editor.per-check-thresholds",
        source=source,
        service=service,
        variables={
            "decision_checks": checks,
            "decision_state": lambda: {
                "text": "Original.",
                "passages": [{"id": "s1", "text": "Original."}],
                "history": [],
                "writing_style": "Concrete prose",
                "prose_rules": [],
            },
            "revision_method": "rewrite",
            "info": SimpleNamespace(text="Original."),
        },
    ).run()
    stage.provider.handler = None
    await route.send("snapshot")
    return route.frames


async def action_taken(stage):
    stage.answer(0.93)
    service, route = stage.start()
    await stage.create(
        uid="editor.action-taken", source=TEMPLATE, service=service
    ).run()
    await route.send("snapshot")
    return route.frames


async def readable_checks(stage):
    from talemate.world_state.templates.decision_checks import (
        default_writing_style_decision_checks,
    )

    checks = default_writing_style_decision_checks()
    checks[0].threshold = 0.91
    checks[1].threshold = 0.76

    async def answer(request):
        probabilities = {"s1_repetition": 0.91, "s2_style": 0.7599999}
        return ProviderResponse(
            answers={
                key: {"type": "noul", "p_true": probabilities.get(key, 0)}
                for key in request.questions
            },
            response_body={"diagnostic": "provider reply"},
        )

    stage.provider.handler = answer
    service, route = stage.start()
    source = (
        Path(__file__).parents[2]
        / "src/talemate/prompts/templates/editor/decision-checks.jinja2"
    ).read_text()
    await stage.create(
        uid="editor.readable-checks",
        source=source,
        service=service,
        variables={
            "decision_checks": checks,
            "decision_state": lambda: {
                "text": "She paid the clerk again. The clock showed eleven.",
                "passages": [
                    {"id": "s1", "text": "She paid the clerk again."},
                    {"id": "s2", "text": "The clock showed eleven."},
                ],
                "history": ["She paid the clerk."],
                "writing_style": "Concrete prose",
                "prose_rules": [],
            },
            "revision_method": "rewrite",
            "info": SimpleNamespace(
                text="She paid the clerk again. The clock showed eleven."
            ),
        },
    ).run()
    stage.provider.handler = None
    await route.send("snapshot")
    return route.frames


async def no_reason(stage):
    stage.answer(0.74)
    service, route = stage.start()
    await stage.create(uid="editor.no-reason", source=NO_REASON, service=service).run()
    await route.send("snapshot")
    return route.frames


async def request_failed(stage):
    async def transport_error(request):
        raise DecisionError(FailureCode.TRANSPORT)

    stage.provider.handler = transport_error
    service, route = stage.start()
    await stage.create(
        uid="editor.request-failed", source=TEMPLATE, service=service
    ).run()
    stage.provider.handler = None
    await route.send("snapshot")
    return route.frames


async def request_not_sent(stage):
    service, route = stage.start(enabled=False)
    await stage.create(
        uid="editor.request-not-sent", source=TEMPLATE, service=service
    ).run()
    await route.send("snapshot")
    return route.frames


async def concurrent(stage):
    """Two invocations in flight; neither may collect the other's outcome."""
    started, release = asyncio.Event(), asyncio.Event()

    def answer(p_true):
        return ProviderResponse(
            answers={"repeats": {"type": "noul", "p_true": p_true}},
            response_body={"repeats": {"noul": p_true}},
        )

    async def hold(request):
        if started.is_set():
            return answer(0.93)
        started.set()
        await release.wait()
        return answer(0.74)

    stage.provider.handler = hold
    service, route = stage.start()
    first = stage.create(uid="editor.concurrent-a", source=TEMPLATE, service=service)
    second = stage.create(uid="editor.concurrent-b", source=TEMPLATE, service=service)
    task = asyncio.create_task(first.run())
    await asyncio.wait_for(started.wait(), 2)
    await asyncio.wait_for(second.run(), 2)
    release.set()
    await asyncio.wait_for(task, 2)
    stage.provider.handler = None
    await route.send("snapshot")
    return route.frames


async def cancelled(stage):
    started = asyncio.Event()

    async def never_answers(request):
        started.set()
        await asyncio.Event().wait()

    stage.provider.handler = never_answers
    service, route = stage.start()
    task = asyncio.create_task(
        stage.create(uid="editor.cancelled", source=TEMPLATE, service=service).run()
    )
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    stage.provider.handler = None
    await route.send("snapshot")
    return route.frames


async def unassociated_action(stage):
    stage.answer(0.74)
    service, route = stage.start()
    await stage.create(
        uid="editor.unassociated", source=UNASSOCIATED, service=service
    ).run()
    await route.send("snapshot")
    return route.frames


async def retention(stage):
    stage.answer(0.74)
    service, route = stage.start(max_finished=2)
    for _ in range(3):
        await stage.create(
            uid="editor.retained", source=TEMPLATE, service=service
        ).run()
    await route.send("snapshot")
    return route.frames


async def clear_keeps_a_pending_action(stage):
    stage.answer(0.93)
    service, route = stage.start()
    await stage.create(uid="editor.cleared", source=TEMPLATE, service=service).run()
    started, release = asyncio.Event(), asyncio.Event()

    async def blocked(**kwargs):
        started.set()
        await release.wait()
        return "rewritten"

    stage.editor.revision_rewrite.side_effect = blocked
    task = asyncio.create_task(
        stage.create(uid="editor.acting", source=TEMPLATE, service=service).run()
    )
    await asyncio.wait_for(started.wait(), 2)
    await route.send("clear")
    release.set()
    await asyncio.wait_for(task, 2)
    stage.editor.revision_rewrite.side_effect = None
    await route.send("snapshot")
    return route.frames


async def cancelled_after_answer(stage):
    """The answer landed; the policy is cancelled before it records an outcome."""
    stage.answer(0.74)
    service, route = stage.start()
    current = {"value": True}

    def cancel():
        current["value"] = False
        return ""

    invocation = stage.create(
        uid="editor.cancelled-after-answer",
        source=CANCEL_AFTER_ANSWER,
        service=service,
        variables={
            "passage": "original",
            "last3": ["earlier"],
            "info": SimpleNamespace(text="original"),
            "cancel": cancel,
        },
        is_current=lambda: current["value"],
    )
    with pytest.raises(GenerationCancelled):
        await invocation.run()
    await route.send("snapshot")
    return route.frames


async def question_types(stage):
    """One request, three question types, three answers on one row."""
    stage.provider.answers = {
        "repeats": {"type": "noul", "p_true": 0.74},
        "tone": {
            "type": "choice",
            "selected": "warm",
            "probabilities": {"warm": 0.7, "cool": 0.3},
            "confidence": 0.8,
        },
        "tension": {
            "type": "score",
            "value": 1.5,
            "probabilities": [0.2, 0.3, 0.5],
            "legend": ["none", "some", "high"],
            "confidence": 0.6,
        },
    }
    stage.provider.raw = {"repeats": {"noul": 0.74}, "tone": "warm", "tension": 1.5}
    service, route = stage.start()
    await stage.create(
        uid="editor.question-types", source=QUESTION_TYPES, service=service
    ).run()
    await route.send("snapshot")
    return route.frames


async def two_asks(stage):
    """Two requests in one invocation; the action names the first."""
    stage.answer(0.74)
    service, route = stage.start()
    await stage.create(uid="editor.two-asks", source=TWO_ASKS, service=service).run()
    await route.send("snapshot")
    return route.frames


async def two_asks_pruned(stage):
    """Retention takes one request of an invocation and keeps its sibling."""
    stage.answer(0.74)
    service, route = stage.start(max_finished=1)
    await stage.create(
        uid="editor.two-asks-pruned", source=TWO_ASKS, service=service
    ).run()
    await route.send("snapshot")
    return route.frames


async def no_request(stage):
    """The one case that makes an invocation a row of its own."""
    service, route = stage.start()
    await stage.create(
        uid="editor.no-request", source=NO_REQUEST, service=service
    ).run()
    await route.send("snapshot")
    return route.frames


async def action_denied(stage):
    """A disabled action is recorded skipped, and the policy takes its fallback."""
    stage.answer(0.93)
    service, route = stage.start()
    await stage.create(
        uid="editor.action-denied",
        source=TEMPLATE,
        service=service,
        actions={
            ("editor", "revision_rewrite"): PolicyAction(
                call=stage.editor.revision_rewrite, enabled=lambda: False
            )
        },
    ).run()
    await route.send("snapshot")
    return route.frames


async def action_failed(stage):
    """The action raised after it started, so the original result is preserved."""
    stage.answer(0.93)
    service, route = stage.start()
    stage.editor.revision_rewrite.side_effect = RuntimeError("editor is unavailable")
    await stage.create(
        uid="editor.action-failed", source=TEMPLATE, service=service
    ).run()
    stage.editor.revision_rewrite.side_effect = None
    await route.send("snapshot")
    return route.frames


SCENARIOS = (
    below_threshold,
    per_check_thresholds,
    readable_checks,
    action_taken,
    no_reason,
    request_failed,
    request_not_sent,
    concurrent,
    cancelled,
    cancelled_after_answer,
    unassociated_action,
    retention,
    clear_keeps_a_pending_action,
    question_types,
    two_asks,
    two_asks_pruned,
    no_request,
    action_denied,
    action_failed,
)


def entries_of(frame):
    if frame["event"] == "snapshot":
        return [*frame["requests"], *frame["invocations"]]
    return [frame["entry"]] if "entry" in frame else []


def substitute(value, names):
    if isinstance(value, dict):
        return {key: substitute(item, names) for key, item in value.items()}
    if isinstance(value, list):
        return [substitute(item, names) for item in value]
    return names.get(value, value) if isinstance(value, str) else value


def normalize(frames):
    """Replaces the identifiers, times and durations that change per run."""
    names = {}

    def register(value, kind):
        if value not in names:
            taken = sum(1 for known in names.values() if known.startswith(kind))
            names[value] = f"{kind}-{taken + 1}"

    for frame in frames:
        for entry in entries_of(frame):
            if "invocation_id" in entry:
                register(entry["invocation_id"], "invocation")
                register(entry["id"], "request")
            else:
                register(entry["id"], "invocation")
            for action in entry["actions"]:
                register(action["id"], "action")
        for key, kind in (("request_ids", "request"), ("invocation_ids", "invocation")):
            for value in frame.get(key, ()):
                register(value, kind)

    positions = {name: index for index, name in enumerate(names.values())}
    frames = substitute(copy.deepcopy(frames), names)
    for frame in frames:
        for entry in entries_of(frame):
            if "timestamp" in entry:
                entry["timestamp"] = (
                    BASE_TIME + timedelta(seconds=positions[entry["id"]])
                ).isoformat()
            if entry.get("elapsed_ms") is not None:
                entry["elapsed_ms"] = REQUEST_MS
            for action in entry["actions"]:
                if action["elapsed_ms"] is not None:
                    action["elapsed_ms"] = ACTION_MS
    return frames


async def test_frontend_fixtures_still_match_the_framework(stage):
    generated = {
        "scenarios": {
            scenario.__name__: normalize(await scenario(stage))
            for scenario in SCENARIOS
        }
    }
    if os.environ.get("TALEMATE_UPDATE_DECISION_FIXTURE"):
        FIXTURE.write_text(json.dumps(generated, indent=2) + "\n")
    assert json.loads(FIXTURE.read_text()) == generated, (
        "The decision log emits frames the frontend fixtures no longer describe. "
        "Regenerate them with TALEMATE_UPDATE_DECISION_FIXTURE=1 and review the diff."
    )
