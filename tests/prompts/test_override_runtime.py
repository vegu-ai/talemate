"""
Prompt.send warns when a template override used by the render explains an empty
response field the code depends on.
"""

from collections import deque
from pathlib import Path
from unittest.mock import patch

import pytest
from structlog.testing import capture_logs

from conftest import client_responses

from talemate.agents.director.response_specs import GUIDANCE_SPEC, MESSAGE_SPEC
from talemate.agents.summarize.analyze_scene import SCENE_ANALYSIS_SPEC
from talemate.prompts import base, groups
from talemate.context import ActiveScene
from talemate.prompts.base import Prompt, prepended_template_dirs
from talemate.prompts.compatibility import rendered_overrides
from talemate.prompts.groups import get_default_template_path
from talemate.prompts.response import ExtractionError

from ._groups_test_helpers import make_template_dir_scene
from .test_base_extras import _FakeClient

DATA_DIR = Path(__file__).parent.parent / "data" / "prompt_compatibility"


@pytest.fixture
def responses():
    token = client_responses.set(deque())
    yield client_responses.get()
    client_responses.reset(token)


@pytest.fixture(autouse=True)
def reported():
    base._reported_override_misses.clear()
    yield
    base._reported_override_misses.clear()


@pytest.fixture
def emitted():
    """Status emits only; send() also emits template_rendered."""
    calls = []
    with patch(
        "talemate.prompts.base.emit",
        side_effect=lambda typ, **kwargs: calls.append(kwargs)
        if typ == "status"
        else None,
    ):
        yield calls


@pytest.fixture
def user_dir(tmp_path, monkeypatch):
    directory = tmp_path / "user"
    monkeypatch.setattr(groups, "_USER_TEMPLATES_DIR", directory)
    return directory


def _override(user_dir: Path, uid: str, content: str) -> Path:
    agent, name = uid.split(".", 1)
    path = user_dir / agent / f"{name}.jinja2"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _default_source(uid: str) -> str:
    agent, name = uid.split(".", 1)
    return get_default_template_path(agent, name).read_text(encoding="utf-8")


def _prompt(uid: str, rendered: str, files: list[Path]) -> Prompt:
    prompt = Prompt.from_text(rendered)
    prompt.render()
    prompt.uid = uid
    prompt._loaded_template_files = [str(path) for path in files]
    return prompt


def _warnings(logs) -> list[dict]:
    return [
        entry
        for entry in logs
        if entry["event"] == "Template override left a response field empty"
    ]


@pytest.mark.asyncio
async def test_identical_override_with_a_flag_gated_anchor_stays_silent(
    responses, emitted, user_dir
):
    uid = "summarizer.analyze-scene-for-next-conversation"
    path = _override(user_dir, uid, _default_source(uid))
    # deep analysis off: the default does not ask for <INVESTIGATE> either
    responses.append("<ANALYSIS>they talk</ANALYSIS>")
    prompt = _prompt(uid, "Analyze inside <ANALYSIS>...</ANALYSIS>", [path])

    with capture_logs() as logs:
        _, extracted = await prompt.send(
            _FakeClient(), response_spec=SCENE_ANALYSIS_SPEC
        )

    assert extracted["investigate"] is None
    assert _warnings(logs) == []
    assert emitted == []


@pytest.mark.asyncio
async def test_override_that_lost_the_anchor(responses, emitted, user_dir):
    uid = "director.guide-conversation"
    path = _override(
        user_dir, uid, (DATA_DIR / "guide-conversation-0.34.jinja2").read_text()
    )
    responses.append("GUIDANCE: be brief")
    prompt = _prompt(uid, "Write your guidance after GUIDANCE:", [path])

    with capture_logs() as logs:
        _, extracted = await prompt.send(_FakeClient(), response_spec=GUIDANCE_SPEC)

    assert extracted["guidance"] is None
    [warning] = _warnings(logs)
    assert warning["template"] == uid
    assert warning["group"] == "user"
    assert warning["key"] == "guidance"
    assert warning["reason"] == "prompt never asks for <GUIDANCE>"

    [status] = emitted
    assert status["status"] == "warning"
    assert status["data"] == {
        "template": uid,
        "group": "user",
        "prompt": uid,
        "key": "guidance",
        "reason": "prompt never asks for <GUIDANCE>",
    }


@pytest.mark.asyncio
async def test_overridden_partial_under_a_default_parent(responses, emitted, user_dir):
    partial = "director.chat-instructions"
    partial_path = _override(
        user_dir, partial, _default_source(partial).replace("<MESSAGE>", "")
    )
    parent_path = get_default_template_path("director", "chat")
    responses.append("Sure, the lighthouse is dark.")
    prompt = _prompt("director.chat", "Answer the user.", [parent_path, partial_path])

    with capture_logs() as logs:
        await prompt.send(_FakeClient(), response_spec=MESSAGE_SPEC)

    [warning] = _warnings(logs)
    assert warning["template"] == partial
    assert warning["prompt"] == "director.chat"
    assert warning["key"] == "message"
    assert len(emitted) == 1


@pytest.mark.asyncio
async def test_required_field_missing_through_an_override_that_lost_it(
    responses, emitted, user_dir
):
    uid = "summarizer.analyze-scene-for-next-conversation"
    include = '{% include "analyze-character-evidence.jinja2" %}'
    source = _default_source(uid)
    assert include in source
    path = _override(
        user_dir, uid, source.replace(include, "").replace("<ANALYSIS>", "")
    )
    responses.append("no analysis here")
    prompt = _prompt(uid, "Analyze the scene.", [path])

    with capture_logs() as logs, pytest.raises(ExtractionError):
        await prompt.send(_FakeClient(), response_spec=SCENE_ANALYSIS_SPEC)

    [warning] = _warnings(logs)
    assert warning["key"] == "analysis"
    assert warning["reason"] == "required field missing"
    assert len(emitted) == 1


@pytest.mark.asyncio
async def test_incomplete_partial_is_not_blamed_for_an_unrelated_field(
    responses, emitted, user_dir
):
    partial = "common.extra-context-static"
    old = (DATA_DIR / "extra-context-static-0.39.jinja2").read_text()
    partial_path = _override(user_dir, partial, old)
    [loaded] = rendered_overrides([str(partial_path)])
    assert loaded.compatibility == "incomplete"
    parent = get_default_template_path(
        "summarizer", "analyze-scene-for-next-conversation"
    )
    responses.append("no analysis here")
    prompt = _prompt(
        "summarizer.analyze-scene-for-next-conversation",
        "Analyze inside <ANALYSIS>...</ANALYSIS>",
        [parent, partial_path],
    )

    with capture_logs() as logs, pytest.raises(ExtractionError):
        await prompt.send(_FakeClient(), response_spec=SCENE_ANALYSIS_SPEC)

    assert _warnings(logs) == []
    assert emitted == []


@pytest.mark.asyncio
async def test_required_field_missing_through_an_identical_override(
    responses, emitted, user_dir
):
    uid = "summarizer.analyze-scene-for-next-conversation"
    path = _override(user_dir, uid, _default_source(uid))
    responses.append("no analysis here")
    prompt = _prompt(uid, "Analyze inside <ANALYSIS>...</ANALYSIS>", [path])

    with capture_logs() as logs, pytest.raises(ExtractionError):
        await prompt.send(_FakeClient(), response_spec=SCENE_ANALYSIS_SPEC)

    assert _warnings(logs) == []
    assert emitted == []


@pytest.mark.asyncio
async def test_model_ignoring_an_asked_anchor_is_not_reported(
    responses, emitted, user_dir
):
    uid = "director.guide-conversation"
    path = _override(
        user_dir, uid, (DATA_DIR / "guide-conversation-0.34.jinja2").read_text()
    )
    responses.append("no tags at all")
    prompt = _prompt(uid, "Put your guidance inside <GUIDANCE>...</GUIDANCE>", [path])

    with capture_logs() as logs:
        await prompt.send(_FakeClient(), response_spec=GUIDANCE_SPEC)

    assert _warnings(logs) == []
    assert emitted == []


@pytest.mark.asyncio
async def test_render_from_defaults_only(responses, emitted):
    responses.append("GUIDANCE: be brief")
    prompt = _prompt(
        "director.guide-conversation",
        "Write your guidance after GUIDANCE:",
        [get_default_template_path("director", "guide-conversation")],
    )

    with capture_logs() as logs:
        await prompt.send(_FakeClient(), response_spec=GUIDANCE_SPEC)

    assert _warnings(logs) == []
    assert emitted == []


@pytest.mark.asyncio
async def test_reported_once_per_template_group_and_key(responses, emitted, user_dir):
    uid = "director.guide-conversation"
    path = _override(
        user_dir, uid, (DATA_DIR / "guide-conversation-0.34.jinja2").read_text()
    )
    for _ in range(3):
        responses.append("GUIDANCE: be brief")
        await _prompt(uid, "after GUIDANCE:", [path]).send(
            _FakeClient(), response_spec=GUIDANCE_SPEC
        )

    assert len(emitted) == 1


def test_render_records_the_files_it_loaded(tmp_path):
    partial = tmp_path / "partial.jinja2"
    partial.write_text("inner", encoding="utf-8")
    token = prepended_template_dirs.set([str(tmp_path)])
    try:
        prompt = Prompt.from_text('outer {% include "partial.jinja2" %}')
        assert "inner" in prompt.render()
    finally:
        prepended_template_dirs.reset(token)

    assert [Path(file).resolve() for file in prompt._loaded_template_files] == [
        partial.resolve()
    ]


@pytest.mark.asyncio
async def test_flat_scene_template_reports_for_the_prompt_agent(
    responses, emitted, tmp_path
):
    scene = make_template_dir_scene(str(tmp_path / "scene-templates"))
    flat = tmp_path / "scene-templates" / "guide-conversation.jinja2"
    flat.parent.mkdir()
    flat.write_text((DATA_DIR / "guide-conversation-0.34.jinja2").read_text())
    responses.append("GUIDANCE: be brief")
    prompt = _prompt("director.guide-conversation", "after GUIDANCE:", [flat])
    prompt.agent_type = "director"

    with ActiveScene(scene), capture_logs() as logs:
        await prompt.send(_FakeClient(), response_spec=GUIDANCE_SPEC)

    [warning] = _warnings(logs)
    assert warning["template"] == "director.guide-conversation"
    assert warning["group"] == "scene"
