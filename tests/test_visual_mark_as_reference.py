"""The "Mark as reference" chain: analysis (tags in the same response when
asked for), tags from the analysis, and the reference mark."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pydantic
import pytest

import talemate.instance as instance
from talemate.agents.visual.analyze import DEFAULT_ANALYSIS_PROMPT, split_analysis_tags
from talemate.agents.visual.backends import Backend
from talemate.agents.visual.nodes import MarkAsReference
from talemate.agents.visual.reference import REFERENCE_TARGETS
from talemate.agents.visual.schema import (
    VIS_TYPE,
    AnalysisRequest,
    BackendStatus,
    BackendStatusType,
)
from talemate.agents.visual.websocket_handler import VisualWebsocketHandler
from talemate.context import ActiveScene
from talemate.game.engine.nodes.core import GraphState
from talemate.game.engine.nodes.registry import get_node
from talemate.game.engine.nodes.tools.analysis import ensure_registry_loaded
from talemate.prompts.response import ExtractionError
from talemate.scene_assets import Asset, AssetMeta

from _node_test_helpers import run_node


class FakeAnalysisBackend(Backend):
    name = "fake"
    label = "Fake"
    image_create = False
    image_edit = False
    image_analyzation = True
    description = "Fake analysis backend for tests."

    status: BackendStatus = pydantic.Field(
        default_factory=lambda: BackendStatus(type=BackendStatusType.OK)
    )
    reply: str = "A lighthouse on a rocky shore at dusk."
    fail: bool = False
    prompts: list[str] = pydantic.Field(default_factory=list)

    async def analyze(self, request, response):
        self.prompts.append(request.prompt)
        if self.fail:
            raise RuntimeError("vision backend unreachable")
        response.analysis = self.reply
        return response


@pytest.fixture
def visual(scene, monkeypatch):
    agent = instance.get_agent("visual")
    monkeypatch.setattr(agent, "backend_image_analyzation", None, raising=False)
    monkeypatch.setattr(scene, "emit_status", Mock(), raising=False)
    monkeypatch.setattr(scene, "active", True, raising=False)
    monkeypatch.setattr(scene, "nodegraph_state", GraphState(), raising=False)
    with ActiveScene(scene):
        yield agent


@pytest.fixture
def vision(visual, monkeypatch):
    backend = FakeAnalysisBackend()
    monkeypatch.setattr(visual, "backend_image_analyzation", backend)
    return backend


@pytest.fixture
def tagger(visual, monkeypatch):
    calls = []

    async def generate_asset_tags(asset_id, text):
        calls.append((asset_id, text))
        if isinstance(tagger.result, Exception):
            raise tagger.result
        return tagger.result

    tagger = SimpleNamespace(calls=calls, result=["shore", "dusk"])
    monkeypatch.setattr(visual, "generate_asset_tags", generate_asset_tags)
    return tagger


def add_asset(scene, vis_type=VIS_TYPE.SCENE_BACKGROUND, **meta) -> Asset:
    asset = Asset(
        id="backdrop",
        file_type="png",
        media_type="image/png",
        meta=AssetMeta(vis_type=vis_type, **meta),
    )
    scene.assets.save_asset(asset)
    return asset


def meta(scene) -> AssetMeta:
    return scene.assets.get_asset("backdrop").meta


def test_the_analysis_and_tags_blocks_are_read():
    analysis, tags = split_analysis_tags(
        "<ANALYSIS>A lighthouse at dusk.</ANALYSIS>\n\n"
        "<TAGS>lighthouse, dusk, , Lighthouse, rocks</TAGS>"
    )

    assert analysis == "A lighthouse at dusk."
    assert tags == ["lighthouse", "dusk", "rocks"]


def test_text_outside_the_blocks_is_left_out():
    analysis, tags = split_analysis_tags(
        "Here you go.\n<ANALYSIS>Para one.\n\nPara two.</ANALYSIS>\n"
        "Keywords:\n<TAGS>a, b</TAGS>\nDone."
    )

    assert analysis == "Para one.\n\nPara two."
    assert tags == ["a", "b"]


def test_keywords_wrapped_over_lines_still_count():
    assert split_analysis_tags("<ANALYSIS>Para.</ANALYSIS><TAGS>a, b,\nc</TAGS>") == (
        "Para.",
        ["a", "b", "c"],
    )


@pytest.mark.parametrize(
    "text",
    [
        "<ANALYSIS>Para.</ANALYSIS>",
        "<ANALYSIS>Para.</ANALYSIS>\n<TAGS>forest, dusk",
        "<ANALYSIS>Para.</ANALYSIS>\nforest, dusk</TAGS>",
        "<ANALYSIS>Para.</ANALYSIS>\n<TAGS> </TAGS>",
        "<ANALYSIS>Para.</ANALYSIS>\n<TAGS>\n- lighthouse\n- sea\n</TAGS>",
    ],
    ids=[
        "no-tags-block",
        "unclosed-tags",
        "close-only-tags",
        "empty-tags",
        "list-form",
    ],
)
def test_no_usable_tags_keep_the_analysis(text):
    assert split_analysis_tags(text) == ("Para.", [])


@pytest.mark.parametrize(
    "text",
    [
        "A lighthouse.",
        "A lighthouse.\n<TAGS>sea, night</TAGS>",
        "<ANALYSIS>A lighthouse.\n<TAGS>sea, night</TAGS>",
        "<ANALYSIS> </ANALYSIS><TAGS>forest, dusk</TAGS>",
    ],
    ids=["no-blocks", "no-analysis-block", "unclosed-analysis", "empty-analysis"],
)
def test_a_response_without_a_usable_analysis_is_refused(text):
    with pytest.raises(ExtractionError):
        split_analysis_tags(text)


async def test_an_analysis_asked_for_tags_saves_both(scene, visual, vision):
    add_asset(scene, tags=["Dusk", "harbour"])
    vision.reply = (
        "<ANALYSIS>A lighthouse at dusk.</ANALYSIS>\n<TAGS>lighthouse, dusk</TAGS>"
    )

    response = await visual.analyze(
        AnalysisRequest(
            prompt="Describe.", asset_id="backdrop", save=True, generate_tags=True
        ),
        await_completion=True,
    )

    assert vision.prompts[0].startswith("Describe.")
    assert "<ANALYSIS>" in vision.prompts[0] and "<TAGS>" in vision.prompts[0]
    assert response.request.prompt == "Describe."
    assert response.analysis == "A lighthouse at dusk."
    assert response.tags == ["lighthouse", "dusk"]
    assert meta(scene).analysis == "A lighthouse at dusk."
    assert meta(scene).tags == ["Dusk", "harbour", "lighthouse"]


async def test_an_analysis_by_default_asks_for_no_tags(scene, visual, vision):
    add_asset(scene)
    vision.reply = "A lighthouse.\n<TAGS>lighthouse</TAGS>"

    response = await visual.analyze(
        AnalysisRequest(prompt="Describe.", asset_id="backdrop", save=True),
        await_completion=True,
    )

    assert vision.prompts == ["Describe."]
    assert response.tags == []
    assert response.analysis == "A lighthouse.\n<TAGS>lighthouse</TAGS>"
    assert meta(scene).tags == []


async def test_the_chain_analyses_tags_and_marks_in_one_call(
    scene, visual, vision, tagger
):
    add_asset(scene)
    vision.reply = (
        "<ANALYSIS>A lighthouse at dusk.</ANALYSIS>\n<TAGS>lighthouse, dusk</TAGS>"
    )

    progress = await visual.mark_as_reference("backdrop")

    assert (progress.analyzed, progress.tagged, progress.marked) == (True, True, True)
    assert progress.errors == []
    assert len(vision.prompts) == 1
    assert tagger.calls == []
    assert meta(scene).analysis == "A lighthouse at dusk."
    assert meta(scene).tags == ["lighthouse", "dusk"]
    assert meta(scene).reference == REFERENCE_TARGETS[VIS_TYPE.SCENE_BACKGROUND]


async def test_without_usable_tags_the_tag_pass_runs_on_the_new_analysis(
    scene, visual, vision, tagger
):
    add_asset(scene)

    progress = await visual.mark_as_reference("backdrop")

    assert tagger.calls == [("backdrop", "A lighthouse on a rocky shore at dusk.")]
    assert (progress.analyzed, progress.tagged, progress.marked) == (True, True, True)
    assert meta(scene).tags == ["shore", "dusk"]


@pytest.mark.parametrize(
    "tags_part",
    [
        "",
        "<TAGS>lighthouse, dusk",
        "<TAGS> </TAGS>",
        "<TAGS>\n- lighthouse\n- dusk\n</TAGS>",
    ],
    ids=["no-tags-block", "unclosed-tags", "empty-tags", "list-form"],
)
async def test_no_usable_tags_go_straight_to_the_tag_pass(
    scene, visual, vision, tagger, tags_part
):
    add_asset(scene)
    vision.reply = f"<ANALYSIS>A lighthouse at dusk.</ANALYSIS>\n{tags_part}"

    progress = await visual.mark_as_reference("backdrop")

    assert len(vision.prompts) == 1
    assert tagger.calls == [("backdrop", "A lighthouse at dusk.")]
    assert meta(scene).analysis == "A lighthouse at dusk."
    assert meta(scene).tags == ["shore", "dusk"]
    assert progress.errors == []


async def test_a_response_that_cannot_be_split_is_analyzed_again_without_tags(
    scene, visual, vision, tagger, monkeypatch
):
    add_asset(scene)
    replies = iter(
        [
            "A lighthouse at dusk, waves.\nThe sea is calm.</TAGS>",
            "A lighthouse at dusk.",
        ]
    )

    async def answer(backend, request, response):
        backend.prompts.append(request.prompt)
        response.analysis = next(replies)
        return response

    monkeypatch.setattr(FakeAnalysisBackend, "analyze", answer)

    progress = await visual.mark_as_reference("backdrop")

    assert "<ANALYSIS>" in vision.prompts[0] and "<TAGS>" in vision.prompts[0]
    assert vision.prompts[1] == DEFAULT_ANALYSIS_PROMPT
    assert meta(scene).analysis == "A lighthouse at dusk."
    assert tagger.calls == [("backdrop", "A lighthouse at dusk.")]
    assert meta(scene).tags == ["shore", "dusk"]
    assert progress.errors == []
    assert progress.marked is True


async def test_a_scene_released_during_the_analysis_gets_nothing_written(
    scene, visual, vision, tagger, monkeypatch
):
    add_asset(scene)

    async def release(backend, request, response):
        scene.active = False
        response.analysis = "A lighthouse at dusk."
        return response

    monkeypatch.setattr(FakeAnalysisBackend, "analyze", release)

    progress = await visual.mark_as_reference("backdrop")

    assert [(e.step, e.message) for e in progress.errors] == [("analysis", "Cancelled")]
    assert progress.finished is True and progress.marked is False
    assert tagger.calls == []
    assert meta(scene).analysis is None
    assert meta(scene).reference == []


async def test_a_release_before_the_retry_sends_no_second_analysis(
    scene, visual, vision, tagger, monkeypatch
):
    add_asset(scene)
    reports = []

    async def broken_then_released(backend, request, response):
        backend.prompts.append(request.prompt)
        scene.active = False
        response.analysis = "A lighthouse at dusk, waves.</TAGS>"
        return response

    async def on_progress(progress):
        reports.append((progress.step, progress.finished))

    monkeypatch.setattr(FakeAnalysisBackend, "analyze", broken_then_released)

    progress = await visual.mark_as_reference("backdrop", on_progress=on_progress)

    assert len(vision.prompts) == 1
    assert [(e.step, e.message) for e in progress.errors] == [("analysis", "Cancelled")]
    assert reports == [("analysis", False), (None, True)]
    assert meta(scene).analysis is None


async def test_a_scene_released_during_tagging_gets_no_tags_or_mark(
    scene, visual, monkeypatch
):
    add_asset(scene, analysis="An old harbour.")
    reports = []

    async def release(asset_id, text):
        scene.active = False
        return ["harbour"]

    async def on_progress(progress):
        reports.append(progress.step)

    monkeypatch.setattr(visual, "generate_asset_tags", release)

    progress = await visual.mark_as_reference("backdrop", on_progress=on_progress)

    assert [(e.step, e.message) for e in progress.errors] == [("tags", "Cancelled")]
    assert progress.marked is False
    assert reports == ["tags", None]
    assert meta(scene).tags == []
    assert meta(scene).reference == []


async def test_an_existing_analysis_is_kept_and_tagged(scene, visual, vision, tagger):
    add_asset(scene, analysis="An old harbour.", tags=["harbour", "Shore"])

    progress = await visual.mark_as_reference("backdrop")

    assert vision.prompts == []
    assert tagger.calls == [("backdrop", "An old harbour.")]
    assert progress.analyzed is False
    assert meta(scene).analysis == "An old harbour."
    assert meta(scene).tags == ["harbour", "Shore", "dusk"]
    assert meta(scene).reference == REFERENCE_TARGETS[VIS_TYPE.SCENE_BACKGROUND]


async def test_without_a_vision_backend_the_image_is_only_marked(scene, visual, tagger):
    add_asset(scene)

    progress = await visual.mark_as_reference("backdrop")

    assert tagger.calls == []
    assert (progress.analyzed, progress.tagged, progress.marked) == (
        False,
        False,
        True,
    )
    assert progress.errors == []
    assert meta(scene).analysis is None
    assert meta(scene).reference == REFERENCE_TARGETS[VIS_TYPE.SCENE_BACKGROUND]


async def test_without_a_vision_backend_an_existing_analysis_is_tagged(
    scene, visual, tagger
):
    add_asset(scene, analysis="An old harbour.")

    progress = await visual.mark_as_reference("backdrop")

    assert tagger.calls == [("backdrop", "An old harbour.")]
    assert progress.tagged is True


def test_every_vis_type_has_reference_targets():
    assert set(REFERENCE_TARGETS) == set(VIS_TYPE)


@pytest.mark.parametrize(
    "vis_type, expected",
    [
        (
            VIS_TYPE.CHARACTER_PORTRAIT,
            [
                VIS_TYPE.CHARACTER_PORTRAIT,
                VIS_TYPE.CHARACTER_CARD,
                VIS_TYPE.SCENE_CARD,
                VIS_TYPE.SCENE_ILLUSTRATION,
            ],
        ),
        (
            VIS_TYPE.CHARACTER_CARD,
            [
                VIS_TYPE.CHARACTER_PORTRAIT,
                VIS_TYPE.CHARACTER_CARD,
                VIS_TYPE.SCENE_CARD,
                VIS_TYPE.SCENE_ILLUSTRATION,
            ],
        ),
        (
            VIS_TYPE.SCENE_BACKGROUND,
            [
                VIS_TYPE.SCENE_BACKGROUND,
                VIS_TYPE.SCENE_ILLUSTRATION,
                VIS_TYPE.CHARACTER_CARD,
            ],
        ),
        (
            VIS_TYPE.SCENE_ILLUSTRATION,
            [VIS_TYPE.SCENE_ILLUSTRATION, VIS_TYPE.SCENE_CARD],
        ),
        (VIS_TYPE.SCENE_CARD, [VIS_TYPE.SCENE_CARD, VIS_TYPE.SCENE_ILLUSTRATION]),
        (
            VIS_TYPE.OBJECT_ILLUSTRATION,
            [VIS_TYPE.OBJECT_ILLUSTRATION, VIS_TYPE.SCENE_ILLUSTRATION],
        ),
    ],
)
async def test_an_image_is_marked_for_what_its_own_type_can_serve(
    scene, visual, tagger, vis_type, expected
):
    add_asset(scene, vis_type=vis_type)

    progress = await visual.mark_as_reference("backdrop")

    assert progress.marked is True
    assert meta(scene).reference == expected


async def test_a_portrait_is_never_marked_as_a_background_reference(
    scene, visual, tagger
):
    add_asset(scene, vis_type=VIS_TYPE.CHARACTER_PORTRAIT)

    await visual.mark_as_reference("backdrop")

    assert VIS_TYPE.SCENE_BACKGROUND not in meta(scene).reference


async def test_an_image_without_a_type_is_not_marked(scene, visual, vision, tagger):
    add_asset(scene, vis_type=VIS_TYPE.UNSPECIFIED)
    reports = []

    async def on_progress(progress):
        reports.append((progress.step, progress.finished))

    progress = await visual.mark_as_reference("backdrop", on_progress=on_progress)

    assert progress.marked is False
    assert [(e.step, e.message) for e in progress.errors] == [
        ("reference", "Give the image a type in the Visual Library first")
    ]
    assert vision.prompts == [] and tagger.calls == []
    assert reports == [(None, True)]
    assert meta(scene).reference == []


def test_the_visual_agent_status_carries_the_reference_targets(visual):
    targets = visual.meta["reference_targets"]

    assert targets["CHARACTER_PORTRAIT"] == [
        "CHARACTER_PORTRAIT",
        "CHARACTER_CARD",
        "SCENE_CARD",
        "SCENE_ILLUSTRATION",
    ]
    assert targets["UNSPECIFIED"] == []


async def test_existing_reference_types_are_kept(scene, visual, tagger):
    add_asset(scene, reference=[VIS_TYPE.CHARACTER_PORTRAIT, VIS_TYPE.SCENE_BACKGROUND])

    await visual.mark_as_reference("backdrop")

    assert meta(scene).reference == [
        VIS_TYPE.CHARACTER_PORTRAIT,
        VIS_TYPE.SCENE_BACKGROUND,
        VIS_TYPE.SCENE_ILLUSTRATION,
        VIS_TYPE.CHARACTER_CARD,
    ]


async def test_a_failed_analysis_still_marks_the_image(scene, visual, vision, tagger):
    add_asset(scene)
    vision.fail = True

    progress = await visual.mark_as_reference("backdrop")

    assert [(e.step, e.message) for e in progress.errors] == [
        ("analysis", "vision backend unreachable")
    ]
    assert tagger.calls == []
    assert progress.marked is True
    assert meta(scene).reference == REFERENCE_TARGETS[VIS_TYPE.SCENE_BACKGROUND]


async def test_a_provider_error_is_reported_by_its_message(
    scene, visual, vision, tagger, monkeypatch
):
    class ProviderError(Exception):
        body = {"message": "no-such-model is not a valid model ID", "code": 400}

    async def refuse(backend, request, response):
        raise ProviderError("Error code: 400 - {'error': {...}, 'user_id': 'user_x'}")

    monkeypatch.setattr(FakeAnalysisBackend, "analyze", refuse)
    add_asset(scene)

    progress = await visual.mark_as_reference("backdrop")

    assert [(e.step, e.message) for e in progress.errors] == [
        ("analysis", "no-such-model is not a valid model ID")
    ]


async def test_failed_tags_keep_the_analysis_and_still_mark(
    scene, visual, vision, tagger
):
    add_asset(scene)
    tagger.result = RuntimeError("summarizer offline")

    progress = await visual.mark_as_reference("backdrop")

    assert [(e.step, e.message) for e in progress.errors] == [
        ("tags", "summarizer offline")
    ]
    assert meta(scene).analysis == "A lighthouse on a rocky shore at dusk."
    assert meta(scene).tags == []
    assert progress.marked is True


async def test_each_step_is_reported_as_it_starts(scene, visual, vision, tagger):
    add_asset(scene)
    reports = []

    async def on_progress(progress):
        reports.append((progress.step, progress.finished))

    await visual.mark_as_reference("backdrop", on_progress=on_progress)

    assert reports == [
        ("analysis", False),
        ("tags", False),
        ("reference", False),
        (None, True),
    ]


async def test_the_tag_pass_is_the_visual_library_handler(scene, visual, monkeypatch):
    ensure_registry_loaded()
    handler = get_node("agents/visual/wshGenerateVisualAssetTags")()
    generate = next(
        node
        for node in handler.nodes.values()
        if node.registry == "agents/summarize/generateTags"
    )
    texts = []

    async def fake_generate(node, state):
        texts.append(node.get_input_value("text"))
        node.set_output_values(
            {"state": node.get_input_value("state"), "tags": ["lighthouse", "dusk"]}
        )

    monkeypatch.setattr(type(generate), "run", fake_generate)
    add_asset(scene)

    tags = await visual.generate_asset_tags("backdrop", "A lighthouse at dusk.")

    assert tags == ["lighthouse", "dusk"]
    assert texts == ["A lighthouse at dusk."]


async def settle(visual):
    await asyncio.gather(*getattr(visual, "_tracked_tasks", {}).values())


async def test_the_websocket_action_reports_progress(scene, visual, tagger):
    add_asset(scene)
    replies = []
    plugin = VisualWebsocketHandler(
        SimpleNamespace(scene=scene, queue_put=replies.append)
    )

    await plugin.handle_mark_as_reference({"asset_id": "backdrop"})
    await settle(visual)

    frames = [r for r in replies if r["action"] == "mark_as_reference_progress"]
    assert [f["step"] for f in frames] == ["reference", None]
    assert frames[-1]["finished"] is True
    assert frames[-1]["marked"] is True


async def test_the_websocket_action_reports_a_missing_image(scene, visual):
    replies = []
    plugin = VisualWebsocketHandler(
        SimpleNamespace(scene=scene, queue_put=replies.append)
    )

    await plugin.handle_mark_as_reference({"asset_id": "gone"})
    await settle(visual)

    assert replies[-1]["finished"] is True
    assert replies[-1]["marked"] is False
    assert replies[-1]["errors"] == [
        {
            "step": "reference",
            "message": "The image is no longer in the Visual Library",
        }
    ]


async def test_the_node_marks_and_reports(scene, visual, tagger):
    add_asset(scene)

    outputs = await run_node(
        MarkAsReference(), scene=scene, inputs={"state": {}, "asset_id": "backdrop"}
    )

    assert outputs["marked"] is True
    assert outputs["analyzed"] is False
    assert outputs["errors"] == []
    assert meta(scene).reference == REFERENCE_TARGETS[VIS_TYPE.SCENE_BACKGROUND]
