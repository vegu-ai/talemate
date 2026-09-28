"""
agent.editor.revision.decision-checks.before: a listener changes the active
decision checks of one revision.
"""

import pytest

import talemate.emit.async_signals as async_signals
from talemate.agents.editor.decision_checks import DecisionChecksEmission

import test_editor_decision_checks

editor_case = test_editor_decision_checks.editor_case
revise = test_editor_decision_checks.revise


@pytest.fixture
def listen():
    connected = []

    def connect(handler):
        signal = async_signals.get("agent.editor.revision.decision-checks.before")
        signal.connect(handler)
        connected.append((signal, handler))

    yield connect
    for signal, handler in connected:
        signal.disconnect(handler)


async def test_listener_sees_the_active_checks(editor_case, listen):
    c = editor_case
    seen = []

    async def handler(emission):
        seen.append(emission)

    listen(handler)
    await revise(c)
    [emission] = seen
    assert isinstance(emission, DecisionChecksEmission)
    assert emission.agent is c.editor
    assert emission.info.text == c.current.message
    assert emission.writing_style == c.scene.test_writing_style.uid
    assert emission.checks and all(check.active for check in emission.checks)


async def test_removing_every_check_runs_the_usual_revision(editor_case, listen):
    c = editor_case

    async def handler(emission):
        emission.checks.clear()

    listen(handler)
    await revise(c)
    assert not c.provider.calls
    c.editor.revision_detect_bad_prose.assert_awaited_once()


async def test_only_the_kept_check_is_asked(editor_case, listen):
    c = editor_case
    kept = []

    async def handler(emission):
        assert len(emission.checks) > 1
        del emission.checks[1:]
        kept.extend(question.id for question in emission.checks[0].questions)

    listen(handler)
    await revise(c)
    [request] = c.provider.calls
    asked = {key.split("_", 1)[1] for key in request.questions}
    assert asked == set(kept)


async def test_editing_a_check_in_place_leaves_the_writing_style_alone(
    editor_case, listen
):
    c = editor_case
    style_checks = c.scene.test_writing_style.decision_checks
    before = [check.model_dump() for check in style_checks]

    async def handler(emission):
        assert not any(check is emission.checks[0] for check in style_checks)
        emission.checks[0].threshold = 0.99
        emission.checks[0].questions[0].question = "Changed for this message"

    listen(handler)
    await revise(c)
    assert [check.model_dump() for check in style_checks] == before
    [request] = c.provider.calls
    assert any(
        "Changed for this message" in q.instructions for q in request.questions.values()
    )
