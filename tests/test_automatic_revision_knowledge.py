from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
import test_actor_perspective_history
from talemate.agents.editor.revision import Issues
import talemate.agents.editor.revision as revision
from talemate.instance import get_agent
from talemate.knowledge.perspectives import set_source_perspectives
from talemate.scene_message import CharacterMessage
from talemate.regenerate import regenerate
from talemate.prompts import Prompt

cast = test_actor_perspective_history.cast


@pytest.fixture
async def automatic_revision(cast, monkeypatch, request, isolate_signals):
    scene, prefix = cast
    mode, failed, method = request.param
    scene.knowledge_eligibility = mode
    editor = get_agent("editor")
    editor.actions["revision"].enabled = True
    editor.actions["revision"].config["automatic_revision"].value = True
    editor.actions["revision"].config["revision_method"].value = method
    editor.actions["revision"].config["min_issues"].value = 1
    monkeypatch.setattr(
        editor,
        "revision_collect_issues",
        AsyncMock(return_value=Issues(repetition_log=["Repeated phrasing."])),
    )
    monkeypatch.setattr(editor, "_emit_revision_diff", AsyncMock())
    if failed:
        set_source_perspectives(
            scene, "message", prefix.id, [{"audience": ["Bob"], "status": "failed"}]
        )
    monkeypatch.setattr(
        get_agent("summarizer"),
        "analyze_perceptions",
        AsyncMock(
            side_effect=AssertionError("Revision must not repair optional history")
        ),
    )
    monkeypatch.setattr(get_agent("summarizer"), "finalize_perceptions", AsyncMock())
    conversation = get_agent("conversation")
    monkeypatch.setattr(conversation, "finalize_message_avatar", AsyncMock())
    monkeypatch.setattr(
        conversation,
        "converse",
        AsyncMock(
            return_value=[
                CharacterMessage(
                    message="Bob: A raw regenerated response with repeated wording."
                )
            ]
        ),
    )
    calls = []
    warnings = Mock()
    monkeypatch.setattr(revision.log, "warning", warnings)

    async def ask(template, client, kind, vars, **kwargs):
        rendered = Prompt.get(template, vars=vars).render()
        calls.append((template, vars, rendered))
        return "", {
            "revision": "He checked the lantern.",
            "fix": "He checked the lantern.",
        }

    monkeypatch.setattr(Prompt, "request", ask)
    isolate_signals("push_history", "push_history.after", "game_loop_new_message")
    scene.signals["push_history"].connect(editor.revision_on_push)
    yield SimpleNamespace(
        scene=scene,
        editor=editor,
        calls=calls,
        failed=failed,
        mode=mode,
        warnings=warnings,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "automatic_revision",
    [
        (mode, failed, method)
        for mode, failed in [
            ("legacy", False),
            ("perception", False),
            ("perception", True),
        ]
        for method in ["rewrite", "unslop"]
    ],
    indirect=True,
)
@pytest.mark.parametrize("path", ["regenerate", "push"])
async def test_automatic_revision_with_optional_history(automatic_revision, path):
    t = automatic_revision
    message = CharacterMessage(message="Bob: A raw response with repeated wording.")
    if path == "regenerate":
        t.scene.history.append(message)
        assert await regenerate(t.scene)
    else:
        await t.scene.push_history(message)
    assert message.versions[-1].source == "revision"
    assert message.message == "Bob: He checked the lantern."
    assert len(t.calls) == 1
    assert t.warnings.call_count == int(t.failed)
    rendered = t.calls[0][2]
    if t.mode == "perception" and not t.failed:
        assert test_actor_perspective_history.PUBLIC_SCRIPT in rendered
        assert "UNSEEN-VAULT-CODE" not in rendered
    else:
        assert test_actor_perspective_history.READER.split(": ", 1)[1] in rendered
        assert "UNSEEN-VAULT-CODE" in rendered


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "automatic_revision", [("perception", False, "unslop")], indirect=True
)
@pytest.mark.parametrize("path", ["regenerate", "push"])
async def test_user_cancel_keeps_unrevised_candidate(
    automatic_revision, monkeypatch, path
):
    from talemate.exceptions import GenerationCancelled

    t = automatic_revision
    statuses = []
    monkeypatch.setattr(revision, "emit", lambda typ, **kw: statuses.append((typ, kw)))

    async def cancel(*args, **kwargs):
        t.scene.cancel_requested = True
        raise GenerationCancelled("Cancelled by user")

    monkeypatch.setattr(Prompt, "request", cancel)
    message = CharacterMessage(message="Bob: Original candidate.")
    if path == "regenerate":
        t.scene.history.append(message)
        await regenerate(t.scene)
    else:
        await t.scene.push_history(message)
    assert all(version.source != "revision" for version in message.versions)
    assert message.message == (
        "Bob: A raw regenerated response with repeated wording."
        if path == "regenerate"
        else "Bob: Original candidate."
    )
    assert any(kw.get("message") == "Revision skipped: cancelled" for _, kw in statuses)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "automatic_revision", [("legacy", False, "unslop")], indirect=True
)
@pytest.mark.parametrize(
    "response,fix,reason",
    [
        ("<NO_FIX_REQUIRED/>", None, None),
        ("<no_fix_required />", None, None),
        ("Malformed response", None, "the response contained no revision"),
        ("", "Expanded content. " * 100, "the revision exceeded the length limit"),
    ],
)
async def test_revision_skip_status(
    automatic_revision, monkeypatch, response, fix, reason
):
    t = automatic_revision
    statuses = []
    monkeypatch.setattr(revision, "emit", lambda typ, **kw: statuses.append((typ, kw)))
    monkeypatch.setattr(
        Prompt,
        "request",
        AsyncMock(
            return_value=(
                response,
                {**revision.FIX_SPEC.extract_all(response), "fix": fix},
            )
        ),
    )
    message = CharacterMessage(message="Bob: Original candidate.")
    assert not await t.editor.maybe_revise_inplace(message)
    skipped = [
        kw["message"]
        for typ, kw in statuses
        if typ == "status" and kw.get("message", "").startswith("Revision skipped:")
    ]
    assert skipped == ([f"Revision skipped: {reason}"] if reason else [])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "automatic_revision",
    [("perception", True, method) for method in ("unslop", "rewrite")],
    indirect=True,
)
@pytest.mark.parametrize("cap", [0, 128])
async def test_old_failed_view_outside_rendered_window_does_not_disable_perspective(
    automatic_revision, monkeypatch, cap
):
    t = automatic_revision
    monkeypatch.setattr(
        type(t.editor.client), "max_token_length", property(lambda _: 4096)
    )
    get_agent("summarizer").actions["manage_scene_history"].config[
        "max_budget"
    ].value = cap
    for index in range(70):
        message = CharacterMessage(
            message=f"Alice: READER-ONLY-{index} " + "hidden details " * 50
        )
        t.scene.history.append(message)
        set_source_perspectives(
            t.scene,
            "message",
            message.id,
            [
                {
                    "audience": ["Bob"],
                    "status": "ready",
                    "text": f"Alice: VISIBLE-VIEW-{index} " + "harbor details " * 50,
                }
            ],
        )
    message = CharacterMessage(message="Bob: A candidate response.")
    await t.scene.push_history(message)
    assert message.versions[-1].source == "revision"
    assert len(t.calls) == 1
    assert "VISIBLE-VIEW-69" in t.calls[0][2]
    assert "READER-ONLY-69" not in t.calls[0][2]
    t.warnings.assert_not_called()
