"""The prompt a backend receives matches its Prompting Type on every
Generate Visual Asset path.

The module runs for real; the LLM client, the backends' HTTP servers and the
vision backend are fakes that record what reaches them.
"""

import asyncio
import base64
import json

import httpx
import pydantic
import pytest

import talemate.agents.visual.generation as generation_module
import talemate.instance as instance
from talemate.agents.visual.backends import Backend
from talemate.agents.visual.backends import automatic1111, comfyui, sdnext
from talemate.agents.visual.schema import (
    GEN_TYPE,
    PROMPT_TYPE,
    VIS_TYPE,
    BackendStatus,
    BackendStatusType,
    VisualPromptPart,
)
from talemate.scene_assets import Asset, AssetMeta

from _node_test_helpers import build_graph, execute_graph, make_capture, make_constant

MODULE = "src/talemate/agents/visual/modules/generate-visual-asset.json"

KEYWORDS = "dark sci-fi cockpit interior, amber fault lights, no people"
STYLE_KEYWORDS = (
    "in the style of a digital artwork, masterpiece, best quality, high detail, "
    "scenery, environment, background, postcard"
)
SENT_KEYWORDS = f"{STYLE_KEYWORDS}, dark sci-fi cockpit interior, amber fault lights"
DESCRIPTIVE = "A dark, claustrophobic cockpit lit by amber fault lights."
REVISED = "The cockpit, as in the reference image, lit by amber fault lights."
REFERENCE = "cockpit-reference"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

OK = BackendStatus(type=BackendStatusType.OK)


class FakeLLM:
    def __init__(self):
        self.requests: list[str] = []
        self.on_revision = None

    async def send_prompt(self, prompt, kind="conversation", **kwargs):
        text = str(prompt)
        if kind.startswith("narrate"):
            self.requests.append("scene_query")
            return "A cramped cockpit with amber fault lights."
        if "<REVISED_PROMPT></REVISED_PROMPT>" in text:
            self.requests.append("revision")
            if self.on_revision:
                self.on_revision()
            return f"<REVISED_PROMPT>{REVISED}</REVISED_PROMPT>"
        if "select_reference" in text:
            self.requests.append("reference_selection")
            call = {
                "name": "select_reference",
                "arguments": {"asset_id": REFERENCE, "purpose": "The cockpit."},
            }
            return f"```json\n{json.dumps(call)}\n```"
        if "<DESCRIPTIVE></DESCRIPTIVE>" in text:
            self.requests.append("prompt_generation")
            return (
                f"<KEYWORDS>{KEYWORDS}</KEYWORDS>"
                f"<DESCRIPTIVE>{DESCRIPTIVE}</DESCRIPTIVE>"
            )
        raise AssertionError(f"unexpected LLM request ({kind}): {text[-300:]}")


class RecordingBackend(Backend):
    name = "recording"
    label = "Recording"
    image_create = True
    image_edit = True
    image_analyzation = False
    description = "Records the requests it receives."

    status: BackendStatus = OK
    requests: list = pydantic.Field(default_factory=list)

    @property
    def max_references(self) -> int:
        return 3

    async def generate(self, request, response):
        self.requests.append(request)
        response.generated = PNG
        return response

    async def cancel_request(self):
        pass


class FakeVision(Backend):
    name = "fake-vision"
    label = "Fake vision"
    image_create = False
    image_edit = False
    image_analyzation = True
    description = "Records analysis requests."

    status: BackendStatus = OK
    analyzed: list[str] = pydantic.Field(default_factory=list)

    async def analyze(self, request, response):
        self.analyzed.append(request.asset_id)
        response.analysis = "A cockpit with amber lights."
        return response


class FakeImageServer:
    def __init__(self):
        self.posts: dict[str, list] = {}

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path != "/upload/image":
            self.posts.setdefault(path, []).append(json.loads(request.content))
        if path == "/object_info":
            return httpx.Response(200, json={})
        if path == "/upload/image":
            return httpx.Response(
                200, json={"name": "ref.png", "subfolder": "talemate"}
            )
        if path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "p1"})
        if path == "/history/p1":
            image = {"filename": "out.png", "subfolder": "", "type": "output"}
            return httpx.Response(
                200, json={"p1": {"outputs": {"9": {"images": [image]}}}}
            )
        if path == "/view":
            return httpx.Response(200, content=PNG)
        if request.method == "GET" and path.startswith("/sdapi/v1/"):
            return httpx.Response(200, json=[])
        if path.startswith("/sdapi/v1/"):
            return httpx.Response(
                200, json={"images": [base64.b64encode(PNG).decode()]}
            )
        return httpx.Response(404)


@pytest.fixture
def visual(scene, monkeypatch):
    from talemate.game.engine.nodes.tools.analysis import ensure_registry_loaded

    ensure_registry_loaded()
    agent = instance.get_agent("visual")
    emitted = []

    def emit(typ, *args, **kwargs):
        emitted.append((typ, kwargs.get("data")))

    async def no_status(*args, **kwargs):
        pass

    monkeypatch.setattr(generation_module, "emit", emit)
    monkeypatch.setattr(agent, "emit_status", no_status)
    monkeypatch.setattr(scene, "emit_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(agent, "backend", None)
    monkeypatch.setattr(agent, "backend_image_edit", None)
    monkeypatch.setattr(agent, "backend_image_analyzation", FakeVision())
    config = agent.actions["prompt_generation"].config
    monkeypatch.setattr(config["revise_edit_prompts"], "value", True)
    monkeypatch.setattr(config["automatic_analysis"], "value", True)

    llm = FakeLLM()
    monkeypatch.setattr(scene.mock_client, "send_prompt", llm.send_prompt)

    scene.assets.save_asset(
        Asset(
            id=REFERENCE,
            file_type="png",
            media_type="image/png",
            meta=AssetMeta(
                vis_type=VIS_TYPE.SCENE_BACKGROUND,
                reference=[VIS_TYPE.SCENE_BACKGROUND],
                tags=["cockpit"],
            ),
        )
    )
    monkeypatch.setattr(
        scene.assets, "get_asset_bytes_many", lambda ids: [PNG for _ in ids]
    )

    agent.test_llm = llm
    agent.test_emitted = emitted
    return agent


def recording(prompt_type: PROMPT_TYPE) -> RecordingBackend:
    return RecordingBackend(prompt_type=prompt_type)


async def run_module(scene, references=None, prompt_only=False) -> dict:
    from talemate.game.engine.nodes.layout import load_graph_from_file

    module, _ = load_graph_from_file(MODULE)
    inputs = {
        "state": True,
        "vis_type": "SCENE_BACKGROUND",
        "instructions": "",
        "prompt_only": prompt_only,
    }
    if references is not None:
        inputs["references"] = references
    source = make_constant(**inputs)
    captured = {}
    output = make_capture(captured, "visual_prompt", "generation_request")
    graph = build_graph(source, module, output)
    for name in inputs:
        graph.connect(source.get_output_socket(name), module.get_input_socket(name))
    for name in ("visual_prompt", "generation_request"):
        graph.connect(module.get_output_socket(name), output.get_input_socket(name))
    await execute_graph(scene, graph)
    for _ in range(20):
        await asyncio.sleep(0)
    return captured


def library_prompts(visual) -> list[str]:
    """Prompts of the generated images the Visual Library receives."""
    return [
        data["request"]["prompt"]
        for typ, data in visual.test_emitted
        if typ == "image_generated"
    ]


async def test_text_to_image_keywords_without_references(scene, visual):
    visual.backend = recording(PROMPT_TYPE.KEYWORDS)

    await run_module(scene, references=[])

    (request,) = visual.backend.requests
    assert request.gen_type == GEN_TYPE.TEXT_TO_IMAGE
    assert request.prompt == SENT_KEYWORDS
    assert "people" in request.negative_prompt.split(", ")
    assert library_prompts(visual) == [SENT_KEYWORDS]
    assert visual.test_llm.requests == ["scene_query", "prompt_generation"]


async def test_text_to_image_descriptive_without_references(scene, visual):
    visual.backend = recording(PROMPT_TYPE.DESCRIPTIVE)

    await run_module(scene, references=[])

    (request,) = visual.backend.requests
    assert request.prompt == DESCRIPTIVE
    assert library_prompts(visual) == [DESCRIPTIVE]


async def test_image_edit_keywords_with_references_skips_revision_and_analysis(
    scene, visual
):
    visual.backend = recording(PROMPT_TYPE.DESCRIPTIVE)
    visual.backend_image_edit = recording(PROMPT_TYPE.KEYWORDS)

    await run_module(scene, references=[REFERENCE])

    assert visual.backend.requests == []
    (request,) = visual.backend_image_edit.requests
    assert request.gen_type == GEN_TYPE.IMAGE_EDIT
    assert request.reference_assets == [REFERENCE]
    assert request.prompt == SENT_KEYWORDS
    assert library_prompts(visual) == [SENT_KEYWORDS]
    assert visual.test_llm.requests == ["scene_query", "prompt_generation"]
    assert visual.backend_image_analyzation.analyzed == []


async def test_image_edit_keywords_with_selected_references_skips_revision(
    scene, visual
):
    visual.backend = recording(PROMPT_TYPE.KEYWORDS)
    visual.backend_image_edit = recording(PROMPT_TYPE.KEYWORDS)

    await run_module(scene)

    (request,) = visual.backend_image_edit.requests
    assert request.reference_assets == [REFERENCE]
    assert request.prompt == SENT_KEYWORDS
    assert library_prompts(visual) == [SENT_KEYWORDS]
    assert visual.test_llm.requests == [
        "scene_query",
        "prompt_generation",
        "reference_selection",
    ]
    assert visual.backend_image_analyzation.analyzed == []


async def test_image_edit_descriptive_with_references_is_revised(scene, visual):
    visual.backend = recording(PROMPT_TYPE.KEYWORDS)
    visual.backend_image_edit = recording(PROMPT_TYPE.DESCRIPTIVE)

    await run_module(scene, references=[REFERENCE])

    (request,) = visual.backend_image_edit.requests
    assert request.prompt == REVISED
    assert library_prompts(visual) == [REVISED]
    assert visual.test_llm.requests == ["scene_query", "prompt_generation", "revision"]
    assert visual.backend_image_analyzation.analyzed == [REFERENCE]


async def test_a_backend_lost_during_the_revision_still_gets_the_keywords(
    scene, visual
):
    """Stage 4 and the request each select a backend; readiness can change between."""
    visual.backend = recording(PROMPT_TYPE.KEYWORDS)
    visual.backend_image_edit = recording(PROMPT_TYPE.DESCRIPTIVE)

    def edit_backend_drops():
        visual.backend_image_edit.status = BackendStatus(type=BackendStatusType.ERROR)

    visual.test_llm.on_revision = edit_backend_drops

    await run_module(scene, references=[REFERENCE])

    assert visual.backend_image_edit.requests == []
    (request,) = visual.backend.requests
    assert request.gen_type == GEN_TYPE.TEXT_TO_IMAGE
    assert request.prompt == SENT_KEYWORDS
    assert "people" in request.negative_prompt.split(", ")
    assert visual.test_llm.requests == ["scene_query", "prompt_generation", "revision"]


async def test_a_weighted_keyword_survives_the_revision(scene, visual, monkeypatch):
    def apply_weighted_style(prompt, vis_type):
        style = VisualPromptPart(
            positive_keywords_raw=["(dim lighting, no people:1.2)", "no watermark"],
            negative_keywords_raw=["(blurry, lowres:1.3)"],
        )
        prompt.parts.insert(0, style)
        return prompt

    monkeypatch.setattr(visual, "apply_styles", apply_weighted_style)
    visual.backend = recording(PROMPT_TYPE.KEYWORDS)
    visual.backend_image_edit = recording(PROMPT_TYPE.DESCRIPTIVE)
    visual.test_llm.on_revision = lambda: setattr(
        visual.backend_image_edit,
        "status",
        BackendStatus(type=BackendStatusType.ERROR),
    )

    await run_module(scene, references=[REFERENCE])

    (request,) = visual.backend.requests
    assert request.prompt == (
        "(dim lighting, no people:1.2), dark sci-fi cockpit interior, amber fault lights"
    )
    assert request.negative_prompt == "(blurry, lowres:1.3), watermark, people"
    assert visual.test_llm.requests == ["scene_query", "prompt_generation", "revision"]


@pytest.mark.parametrize(
    "references", [[], ["missing-asset"]], ids=["empty", "unknown"]
)
async def test_no_usable_reference_skips_revision_and_analysis(
    scene, visual, references
):
    visual.backend = recording(PROMPT_TYPE.DESCRIPTIVE)
    visual.backend_image_edit = recording(PROMPT_TYPE.DESCRIPTIVE)

    await run_module(scene, references=references)

    assert visual.backend_image_edit.requests == []
    (request,) = visual.backend.requests
    assert request.gen_type == GEN_TYPE.TEXT_TO_IMAGE
    assert request.prompt == DESCRIPTIVE
    assert visual.test_llm.requests == ["scene_query", "prompt_generation"]
    assert visual.backend_image_analyzation.analyzed == []


async def test_text_to_image_keywords_with_an_empty_reference_list(scene, visual):
    """An empty list still opens References given; the revision stays off."""
    visual.backend = recording(PROMPT_TYPE.KEYWORDS)
    visual.backend_image_edit = recording(PROMPT_TYPE.DESCRIPTIVE)

    await run_module(scene, references=[])

    assert visual.backend_image_edit.requests == []
    (request,) = visual.backend.requests
    assert request.gen_type == GEN_TYPE.TEXT_TO_IMAGE
    assert request.prompt == SENT_KEYWORDS
    assert visual.test_llm.requests == ["scene_query", "prompt_generation"]


async def test_image_edit_keywords_without_references(scene, visual):
    visual.backend_image_edit = recording(PROMPT_TYPE.KEYWORDS)

    await run_module(scene, references=[])

    (request,) = visual.backend_image_edit.requests
    assert request.gen_type == GEN_TYPE.IMAGE_EDIT
    assert request.reference_assets == []
    assert request.prompt == SENT_KEYWORDS
    assert visual.test_llm.requests == ["scene_query", "prompt_generation"]


@pytest.mark.parametrize(
    ("prompt_type", "expected"),
    [(PROMPT_TYPE.KEYWORDS, SENT_KEYWORDS), (PROMPT_TYPE.DESCRIPTIVE, DESCRIPTIVE)],
)
async def test_prompt_only_uses_the_fallback_prompt_type(
    scene, visual, monkeypatch, prompt_type, expected
):
    monkeypatch.setattr(
        visual.actions["prompt_generation"].config["fallback_prompt_type"],
        "value",
        prompt_type,
    )

    captured = await run_module(scene, references=[REFERENCE], prompt_only=True)

    assert captured["visual_prompt"].positive_prompt == expected
    assert library_prompts(visual) == []
    assert visual.test_llm.requests == ["scene_query", "prompt_generation"]


@pytest.fixture
def image_server(monkeypatch):
    server = FakeImageServer()
    transport = httpx.MockTransport(server.handle)
    real_client = httpx.AsyncClient

    def client(*args, **kwargs):
        kwargs.pop("timeout", None)
        return real_client(*args, transport=transport, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    return server


def comfyui_prompt(payload: dict) -> str:
    (node,) = [
        node
        for node in payload["prompt"].values()
        if node.get("_meta", {}).get("title") == "Talemate Positive Prompt"
    ]
    return node["inputs"].get("text") or node["inputs"].get("prompt")


async def test_comfyui_keywords_image_edit_sends_the_keywords(
    scene, visual, image_server, monkeypatch
):
    actions = visual.actions
    monkeypatch.setattr(
        actions["comfyui_image_edit"].config["workflow"],
        "value",
        "qwen_image_edit.json",
    )
    monkeypatch.setattr(
        actions["comfyui_image_edit"].config["prompt_type"],
        "value",
        PROMPT_TYPE.KEYWORDS,
    )
    backend = await visual._comfyui_backend(None, "comfyui_image_edit", {}, force=True)
    backend.status = OK
    visual.backend_image_edit = backend

    await run_module(scene, references=[REFERENCE])
    for _ in range(30):
        if library_prompts(visual):
            break
        await asyncio.sleep(0.1)

    (payload,) = image_server.posts["/prompt"]
    assert comfyui_prompt(payload) == SENT_KEYWORDS
    assert library_prompts(visual) == [SENT_KEYWORDS]
    assert visual.test_llm.requests == ["scene_query", "prompt_generation"]


async def test_comfyui_keywords_text_to_image_sends_the_keywords(
    scene, visual, image_server, monkeypatch
):
    monkeypatch.setattr(
        visual.actions["comfyui_image_create"].config["prompt_type"],
        "value",
        PROMPT_TYPE.KEYWORDS,
    )
    backend = await visual._comfyui_backend(
        None, "comfyui_image_create", {}, force=True
    )
    backend.status = OK
    visual.backend = backend

    await run_module(scene, references=[])
    for _ in range(30):
        if library_prompts(visual):
            break
        await asyncio.sleep(0.1)

    (payload,) = image_server.posts["/prompt"]
    assert comfyui_prompt(payload) == SENT_KEYWORDS
    assert library_prompts(visual) == [SENT_KEYWORDS]


@pytest.mark.parametrize(
    ("action_name", "references", "endpoint"),
    [
        ("sdnext_image_create", [], "/sdapi/v1/txt2img"),
        ("sdnext_image_edit", [REFERENCE], "/sdapi/v1/img2img"),
    ],
)
async def test_sdnext_keywords_sends_the_keywords(
    scene, visual, image_server, monkeypatch, action_name, references, endpoint
):
    monkeypatch.setattr(
        visual.actions[action_name].config["prompt_type"], "value", PROMPT_TYPE.KEYWORDS
    )
    backend = sdnext.Backend(
        api_url="http://sdnext.test", prompt_type=PROMPT_TYPE.KEYWORDS
    )
    backend = await visual._sdnext_backend(backend, action_name)
    backend.status = OK
    if action_name == "sdnext_image_create":
        visual.backend = backend
    else:
        visual.backend_image_edit = backend

    await run_module(scene, references=references)
    for _ in range(30):
        if library_prompts(visual):
            break
        await asyncio.sleep(0.1)

    (payload,) = image_server.posts[endpoint]
    assert payload["prompt"] == SENT_KEYWORDS
    assert library_prompts(visual) == [SENT_KEYWORDS]
    assert visual.test_llm.requests == ["scene_query", "prompt_generation"]


async def test_automatic1111_keywords_sends_the_keywords(
    scene, visual, image_server, monkeypatch
):
    visual.backend = automatic1111.Backend(
        api_url="http://a1111.test", prompt_type=PROMPT_TYPE.DESCRIPTIVE, status=OK
    )
    monkeypatch.setattr(
        visual.actions["automatic1111_image_create"].config["prompt_type"],
        "value",
        PROMPT_TYPE.KEYWORDS,
    )
    visual.backend = await visual.automatic1111_backend(old_config=None)

    await run_module(scene, references=[])
    for _ in range(30):
        if library_prompts(visual):
            break
        await asyncio.sleep(0.1)

    (payload,) = image_server.posts["/sdapi/v1/txt2img"]
    assert payload["prompt"] == SENT_KEYWORDS
    assert library_prompts(visual) == [SENT_KEYWORDS]


@pytest.mark.parametrize(
    ("builder", "action_name", "backend_class"),
    [
        ("automatic1111_backend", "automatic1111_image_create", automatic1111.Backend),
        ("comfyui_backend", "comfyui_image_create", comfyui.Backend),
        ("comfyui_backend_image_edit", "comfyui_image_edit", comfyui.Backend),
    ],
)
async def test_a_prompt_type_change_reaches_the_existing_backend(
    scene, visual, monkeypatch, builder, action_name, backend_class
):
    existing = backend_class(
        api_url="http://image.test", prompt_type=PROMPT_TYPE.DESCRIPTIVE
    )
    attribute = "backend_image_edit" if action_name.endswith("_edit") else "backend"
    monkeypatch.setattr(visual, attribute, existing)
    api_url = visual.actions[action_name].config["api_url"]
    monkeypatch.setattr(api_url, "value", "http://image.test")
    old_config = {action_name: visual.actions[action_name].model_copy(deep=True)}
    monkeypatch.setattr(
        visual.actions[action_name].config["prompt_type"], "value", PROMPT_TYPE.KEYWORDS
    )

    backend = await getattr(visual, builder)(old_config=old_config)

    assert backend is existing
    assert backend.prompt_type == PROMPT_TYPE.KEYWORDS
