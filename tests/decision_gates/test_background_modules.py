import asyncio
import io
from typing import ClassVar

import pydantic
import pytest
from PIL import Image

from talemate.agents.visual.agent import VisualAgent
from talemate.agents.visual.backends import Backend
from talemate.agents.visual.schema import (
    GEN_TYPE,
    PROMPT_TYPE,
    BackendStatus,
    BackendStatusType,
)
from talemate.events import GameLoopNewMessageEvent
from talemate.game.engine.nodes.core import GraphContext
from talemate.game.engine.nodes.layout import load_graph_from_file
from talemate.game.engine.nodes.tools.analysis import ensure_registry_loaded
from talemate.instance import get_agent
from talemate.prompts import Prompt
from talemate.scene_assets import VIS_TYPE, Asset, AssetMeta
from talemate.scene_message import (
    CharacterMessage,
    DirectorMessage,
    NarratorMessage,
    SceneBackdropMessage,
)

PURPOSE = "world_state.scene_background"
EVENT_MODULE = "src/talemate/agents/world_state/modules/on-message-set-background.json"

SELECTION_REPLY = (
    "<ASSET_ID></ASSET_ID><NAME>Harbour at dawn</NAME>"
    "<INSTRUCTIONS>The harbour at dawn, mist on the water</INSTRUCTIONS>"
    "<REFERENCES>harbour-night</REFERENCES>"
)


class GatedBackend(Backend):
    name: ClassVar[str] = "gated"
    label: ClassVar[str] = "Gated"
    image_create: ClassVar[bool] = True
    image_edit: ClassVar[bool] = False
    image_analyzation: ClassVar[bool] = False
    description: ClassVar[str] = "Test backend that waits for release"
    prompt_type: PROMPT_TYPE = PROMPT_TYPE.DESCRIPTIVE
    status: BackendStatus = BackendStatus(type=BackendStatusType.OK)
    requests: list = pydantic.Field(default_factory=list)
    _release: asyncio.Event = pydantic.PrivateAttr(default_factory=asyncio.Event)

    @property
    def release(self) -> asyncio.Event:
        return self._release

    async def generate(self, request, response):
        self.requests.append(request)
        await self._release.wait()
        buffer = io.BytesIO()
        Image.new("RGB", (4, 2), "navy").save(buffer, format="PNG")
        response.generated = buffer.getvalue()
        return response

    async def cancel_request(self):
        pass


@pytest.fixture
def case(gate_case, monkeypatch, tmp_path):
    c = gate_case
    ensure_registry_loaded()
    c.scene.project_name = "background-module-test"
    monkeypatch.setattr(c.scene, "scenes_dir", lambda: str(tmp_path))
    asset_dir = tmp_path / c.scene.project_name / "assets"
    asset_dir.mkdir(parents=True)
    for name in ("harbour-day", "harbour-night"):
        Image.new("RGB", (4, 2), "blue").save(asset_dir / f"{name}.png")
    c.scene.assets._assets_cache = {
        name: Asset(
            id=name,
            file_type="png",
            media_type="image",
            meta=AssetMeta(name=name, tags=[name], vis_type=VIS_TYPE.SCENE_BACKGROUND),
        )
        for name in ("harbour-day", "harbour-night")
    }
    c.scene.assets.backdrop = "harbour-day"

    config = c.agent.actions["backgrounds"].config
    config["selection_frequency"].value = 1
    c.config = config

    visual = get_agent("visual")
    monkeypatch.setattr(VisualAgent, "can_generate_images", property(lambda s: True))
    monkeypatch.setattr(VisualAgent, "can_edit_images", property(lambda s: False))
    monkeypatch.setattr(VisualAgent, "backend", None, raising=False)
    visual.backend = GatedBackend()

    async def no_finalize(request):
        pass

    monkeypatch.setattr(visual, "finalize_prompt_request", no_finalize)
    c.visual = visual

    c.prompts = []

    async def send(prompt, *args, **kwargs):
        text = str(prompt.vars.get("instructions", ""))
        c.prompts.append(text)
        if "Available backgrounds" in text:
            return c.selection_reply
        if "REVISED_PROMPT" in text:
            return "<REVISED_PROMPT>A misty harbour at night, lanterns lit</REVISED_PROMPT>"
        return "<KEYWORDS>harbour, dawn</KEYWORDS><DESCRIPTIVE>A misty harbour</DESCRIPTIVE>"

    c.selection_reply = SELECTION_REPLY
    monkeypatch.setattr(Prompt, "send", send)
    return c


def selection_prompts(c) -> int:
    return sum("Available backgrounds" in text for text in c.prompts)


def backdrops(scene) -> list[tuple]:
    return [
        (m.backdrop, m.previous_backdrop, m.pending)
        for m in scene.history
        if isinstance(m, SceneBackdropMessage)
    ]


async def on_message(c, message):
    c.scene.history.append(message)
    module, _ = load_graph_from_file(EVENT_MODULE)
    with GraphContext():
        await module.execute_from_event(
            GameLoopNewMessageEvent(
                scene=c.scene, event_type="game_loop_new_message", message=message
            )
        )


async def settle():
    for _ in range(20):
        await asyncio.sleep(0)


async def test_frequency_zero_checks_nothing(case):
    case.config["selection_frequency"].value = 0

    await on_message(case, NarratorMessage("Dawn breaks over the harbour."))

    assert case.prompts == [] and not case.provider.calls
    assert backdrops(case.scene) == []


async def test_only_story_messages_are_checked(case):
    await on_message(case, DirectorMessage("Make it dawn.", source="director"))

    assert case.prompts == [] and not case.provider.calls


async def test_a_confident_decision_switches_to_an_existing_background(case):
    case.provider.answers = {
        "fits_current": {"type": "noul", "p_true": 0.01},
        "background": {
            "type": "choice",
            "selected": "harbour-night",
            "probabilities": {"harbour-day": 0.01, "harbour-night": 0.98, "none": 0.01},
            "confidence": 0.99,
        },
    }

    await on_message(case, CharacterMessage("Mara: It is dark already."))

    assert selection_prompts(case) == 0
    assert case.scene.assets.backdrop == "harbour-night"
    assert backdrops(case.scene) == [("harbour-night", "harbour-day", False)]


async def test_a_current_background_that_fits_changes_nothing(case):
    case.provider.answers = {"fits_current": {"type": "noul", "p_true": 0.99}}

    await on_message(case, NarratorMessage("The morning sun warms the quay."))

    assert case.scene.assets.backdrop == "harbour-day"
    assert backdrops(case.scene) == []


async def test_no_fit_generates_a_new_background_when_allowed(case):
    case.config["decision_model"].value = False
    case.config["generate_new"].value = True

    await on_message(case, NarratorMessage("Dawn breaks over the harbour."))

    await settle()
    assert selection_prompts(case) == 1
    (request,) = case.visual.backend.requests
    assert request.purpose == PURPOSE
    assert not any("REVISED_PROMPT" in text for text in case.prompts)
    assert request.vis_type == VIS_TYPE.SCENE_BACKGROUND
    assert request.asset_attachment_context.scene_backdrop
    assert request.asset_attachment_context.asset_name == "Harbour at dawn"
    assert backdrops(case.scene) == [(None, "harbour-day", True)]
    assert case.visual.generations_running(PURPOSE) == 1

    case.visual.backend.release.set()
    await settle()

    (generated,) = [
        m.backdrop for m in case.scene.history if isinstance(m, SceneBackdropMessage)
    ]
    assert case.scene.assets.backdrop == generated
    assert case.scene.assets.get_asset(generated).meta.name == "Harbour at dawn"
    assert backdrops(case.scene) == [(generated, "harbour-day", False)]
    assert case.visual.generations_running(PURPOSE) == 0


async def test_no_fit_without_generate_new_keeps_the_background(case):
    case.config["decision_model"].value = False

    await on_message(case, NarratorMessage("Dawn breaks over the harbour."))

    assert selection_prompts(case) == 1
    assert "Available backgrounds" in case.prompts[0]
    assert "<NAME>" not in case.prompts[0]
    current = case.prompts[0].split("Current background")[1].split("Task")[0]
    assert "Name: harbour-day" in current
    assert case.visual.backend.requests == []
    assert backdrops(case.scene) == []


async def test_a_running_background_generation_skips_the_check(case):
    case.config["decision_model"].value = False
    case.config["generate_new"].value = True
    await on_message(case, NarratorMessage("Dawn breaks over the harbour."))
    await settle()

    await on_message(case, NarratorMessage("Gulls cry over the water."))

    assert selection_prompts(case) == 1
    assert len(case.visual.backend.requests) == 1

    case.visual.backend.release.set()
    await settle()


async def test_the_frequency_checks_every_nth_story_message(case):
    case.config["selection_frequency"].value = 2
    case.provider.answers = {"fits_current": {"type": "noul", "p_true": 0.99}}

    for text in ("One.", "Two.", "Three."):
        await on_message(case, NarratorMessage(text))

    assert len(case.provider.calls) == 2


async def test_a_failed_check_is_reported_and_the_story_continues(case, monkeypatch):
    case.config["decision_model"].value = False
    statuses = []

    async def fail(prompt, *args, **kwargs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(Prompt, "send", fail)
    import talemate.game.engine.nodes.event as event_nodes

    monkeypatch.setattr(
        event_nodes,
        "emit",
        lambda typ, message=None, **kw: statuses.append(
            (typ, message, kw.get("status"))
        ),
    )

    await on_message(case, NarratorMessage("Dawn breaks over the harbour."))

    assert (
        "status",
        "Scene background check failed: model unavailable",
        "error",
    ) in statuses


async def test_named_references_turn_the_generation_into_an_image_edit(
    case, monkeypatch
):
    case.config["decision_model"].value = False
    case.config["generate_new"].value = True
    monkeypatch.setattr(VisualAgent, "can_edit_images", property(lambda s: True))
    monkeypatch.setattr(VisualAgent, "backend_image_edit", None, raising=False)
    case.visual.backend_image_edit = case.visual.backend

    await on_message(case, NarratorMessage("Dawn breaks over the harbour."))
    await settle()

    (request,) = case.visual.backend.requests
    assert request.gen_type == GEN_TYPE.IMAGE_EDIT
    assert request.reference_assets == ["harbour-night"]
    assert not any("select_reference" in text for text in case.prompts)
    assert any("REVISED_PROMPT" in text for text in case.prompts), "edit prompt revised"
    assert "lanterns lit" in request.prompt

    case.visual.backend.release.set()
    await settle()
