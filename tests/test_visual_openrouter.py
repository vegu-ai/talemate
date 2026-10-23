"""
The Visualizer's OpenRouter backend (#730): the model lists it offers, the
typed model input, and the Image API path of the models that output images
only - those refuse chat completions.
"""

import base64
import io
from types import SimpleNamespace
from unittest import mock

import httpx
import pytest
from PIL import Image

import talemate.agents.visual.backends.openrouter as backend_module
import talemate.client.openrouter as openrouter_client
from talemate.agents.visual.agent import VisualAgent
from talemate.agents.visual.backends import BackendStatusType
from talemate.agents.visual.backends.openrouter import Backend as OpenRouterBackend
from talemate.agents.visual.backends.openrouter import nearest_aspect_ratio
from talemate.agents.visual.schema import (
    FORMAT_TYPE,
    GEN_TYPE,
    GenerationRequest,
    GenerationResponse,
)

OPENROUTER_ACTIONS = (
    "openrouter_image_create",
    "openrouter_image_edit",
    "openrouter_image_analyzation",
)

# listed parameters as the live GET /api/v1/images/models gave them (2026-09-22)
IMAGE_MODELS = {
    "black-forest-labs/flux.2-pro": openrouter_client.ImageModel(
        id="black-forest-labs/flux.2-pro",
        output_modalities=["image"],
        aspect_ratios=["1:1", "4:3", "3:4", "3:2", "2:3", "16:9", "9:16", "auto"],
        output_formats=["png", "jpeg"],
        min_references=0,
        max_references=8,
    ),
    "google/gemini-3-pro-image-preview": openrouter_client.ImageModel(
        id="google/gemini-3-pro-image-preview",
        output_modalities=["image", "text"],
        aspect_ratios=["1:1", "16:9", "9:16"],
        min_references=0,
        max_references=14,
    ),
    "inclusionai/ming-image-0.1-design": openrouter_client.ImageModel(
        id="inclusionai/ming-image-0.1-design",
        output_modalities=["image"],
        output_formats=["png", "jpeg", "webp"],
        min_references=0,
        max_references=0,
    ),
    "krea/krea-2-medium": openrouter_client.ImageModel(
        id="krea/krea-2-medium",
        output_modalities=["image"],
        aspect_ratios=["1:1", "16:9", "9:16"],
        min_references=0,
        max_references=1,
    ),
    "meta/muse-image": openrouter_client.ImageModel(
        id="meta/muse-image", output_modalities=["image"]
    ),
    "openai/gpt-image-1": openrouter_client.ImageModel(
        id="openai/gpt-image-1",
        output_modalities=["image"],
        aspect_ratios=["1:1", "3:2", "2:3", "auto"],
        min_references=0,
        max_references=16,
    ),
    "recraft/recraft-v4-styles": openrouter_client.ImageModel(
        id="recraft/recraft-v4-styles",
        output_modalities=["image"],
        aspect_ratios=["1:1", "16:9", "9:16"],
        min_references=1,
        max_references=10,
    ),
    "recraft/recraft-v4-vector": openrouter_client.ImageModel(
        id="recraft/recraft-v4-vector",
        output_modalities=["image"],
        output_formats=["svg"],
        min_references=0,
        max_references=1,
    ),
}
# SVG-only models are in neither list; reference-only models cannot make an
# image from text; Ming takes no references
TEXT_TO_IMAGE_CHOICES = [
    "black-forest-labs/flux.2-pro",
    "google/gemini-3-pro-image-preview",
    "inclusionai/ming-image-0.1-design",
    "krea/krea-2-medium",
    "meta/muse-image",
    "openai/gpt-image-1",
]
IMAGE_EDIT_CHOICES = [
    "black-forest-labs/flux.2-pro",
    "google/gemini-3-pro-image-preview",
    "krea/krea-2-medium",
    "meta/muse-image",
    "openai/gpt-image-1",
    "recraft/recraft-v4-styles",
]
TEXT_MODELS = ["a/text-model", "google/gemini-3-flash-preview"]
PROVIDERS = ["Google AI Studio", "Novita"]


@pytest.fixture
def openrouter_lists(monkeypatch):
    monkeypatch.setattr(openrouter_client, "IMAGE_MODELS", dict(IMAGE_MODELS))
    monkeypatch.setattr(openrouter_client, "AVAILABLE_MODELS", list(TEXT_MODELS))
    monkeypatch.setattr(openrouter_client, "AVAILABLE_PROVIDERS", list(PROVIDERS))


@pytest.fixture
def visual_agent():
    return VisualAgent()


def choice_values(field):
    return [choice["value"] for choice in field.choices]


def test_model_fields_accept_a_typed_model_id(visual_agent):
    for action_name in OPENROUTER_ACTIONS:
        model = visual_agent.actions[action_name].config["model"]
        assert model.type == "combobox"
        assert model.required is True


def test_update_choices_offers_image_models_to_generate_and_text_models_to_analyze(
    visual_agent, openrouter_lists
):
    visual_agent.openrouter_update_choices()

    create = visual_agent.actions["openrouter_image_create"].config["model"]
    assert choice_values(create) == TEXT_TO_IMAGE_CHOICES
    edit = visual_agent.actions["openrouter_image_edit"].config["model"]
    assert choice_values(edit) == IMAGE_EDIT_CHOICES
    analysis = visual_agent.actions["openrouter_image_analyzation"].config["model"]
    assert choice_values(analysis) == TEXT_MODELS


def test_update_choices_offers_the_fetched_providers(visual_agent, openrouter_lists):
    visual_agent.openrouter_update_choices()

    for action_name in OPENROUTER_ACTIONS:
        config = visual_agent.actions[action_name].config
        assert choice_values(config["provider_only"]) == PROVIDERS
        assert choice_values(config["provider_ignore"]) == PROVIDERS


async def test_status_emit_fills_openrouter_choices_without_a_saved_backend(
    visual_agent, openrouter_lists
):
    assert visual_agent.actions["_config"].config["backend"].value == ""
    assert visual_agent.backend is None

    await visual_agent.emit_status()

    create = visual_agent.actions["openrouter_image_create"].config
    assert choice_values(create["model"]) == TEXT_TO_IMAGE_CHOICES
    assert choice_values(create["provider_only"]) == PROVIDERS


async def test_a_cleared_model_field_gives_an_error_status(visual_agent):
    visual_agent.actions["openrouter_image_create"].config["model"].value = None

    backend = await visual_agent.openrouter_backend(force=True)
    status = await backend.ready()

    assert backend.model == ""
    assert status.type == BackendStatusType.ERROR
    assert status.message == "No model set"


async def test_connection_check_retries_the_image_model_list(monkeypatch):
    fetches = []

    async def fetch_available_image_models():
        fetches.append(True)
        return {}

    monkeypatch.setattr(
        openrouter_client, "fetch_available_image_models", fetch_available_image_models
    )
    monkeypatch.setattr(
        backend_module,
        "get_config",
        lambda: SimpleNamespace(openrouter=SimpleNamespace(api_key="sk-or-test")),
    )
    client = mock.AsyncMock()
    client.__aenter__.return_value = client
    client.get.return_value = mock.MagicMock(status_code=200)
    monkeypatch.setattr(backend_module.httpx, "AsyncClient", lambda: client)

    status = await OpenRouterBackend(model="meta/muse-image").test_connection()

    assert status.type == BackendStatusType.OK
    assert fetches == [True]


# --- Image API path ---------------------------------------------------------


def image_bytes(image_format: str, size=(64, 32)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, "red").save(buffer, format=image_format)
    return buffer.getvalue()


def image_api_payload(data: bytes, media_type: str) -> dict:
    return {
        "data": [
            {"b64_json": base64.b64encode(data).decode(), "media_type": media_type}
        ]
    }


class FakeImagesResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON")
        return self._payload


class FakeImagesClient:
    def __init__(self, control):
        self._control = control

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None, timeout=None):
        self._control.requests.append(
            {"url": url, "json": json, "headers": headers, "timeout": timeout}
        )
        if isinstance(self._control.response, Exception):
            raise self._control.response
        return self._control.response


@pytest.fixture
def images_api(monkeypatch, openrouter_lists):
    control = SimpleNamespace(
        requests=[],
        response=FakeImagesResponse(
            200, image_api_payload(image_bytes("WEBP"), "image/webp")
        ),
        refreshes=[],
        # what a refreshed list adds to the loaded one
        released_later={},
    )

    async def fetch_available_image_models(refresh=False):
        control.refreshes.append(refresh)
        return {**openrouter_client.IMAGE_MODELS, **control.released_later}

    monkeypatch.setattr(
        openrouter_client, "fetch_available_image_models", fetch_available_image_models
    )
    monkeypatch.setattr(
        backend_module.httpx,
        "AsyncClient",
        lambda *args, **kwargs: FakeImagesClient(control),
    )
    monkeypatch.setattr(
        backend_module,
        "get_config",
        lambda: SimpleNamespace(openrouter=SimpleNamespace(api_key="sk-or-test")),
    )
    monkeypatch.setattr(
        backend_module, "get_agent", lambda name: SimpleNamespace(generate_timeout=42)
    )
    return control


async def generate(backend, **request_fields):
    request = GenerationRequest(**request_fields)
    response = await backend.generate(request, GenerationResponse(request=request))
    return request, response


async def test_image_only_models_use_the_image_api(images_api):
    request, response = await generate(
        OpenRouterBackend(model="meta/muse-image"),
        prompt="a lighthouse at dusk",
        format=FORMAT_TYPE.LANDSCAPE,
    )

    [sent] = images_api.requests
    assert sent["url"] == "https://openrouter.ai/api/v1/images"
    # Muse lists no parameters: no aspect ratio, no output format
    assert sent["json"] == {
        "model": "meta/muse-image",
        "prompt": "a lighthouse at dusk",
    }
    assert sent["headers"] == {"Authorization": "Bearer sk-or-test"}
    assert sent["timeout"] == 42
    # the WebP answer is stored as PNG with its real size
    with Image.open(io.BytesIO(response.generated)) as image:
        assert image.format == "PNG"
    assert (request.resolution.width, request.resolution.height) == (64, 32)


async def test_models_that_also_write_text_keep_chat_completions(
    images_api, monkeypatch
):
    routed = []

    async def generate_text(self, request, response):
        routed.append(self.model)
        return response

    monkeypatch.setattr(OpenRouterBackend, "_generate_text", generate_text)

    await generate(
        OpenRouterBackend(model="google/gemini-3-pro-image-preview"), prompt="x"
    )
    # a listed model is routed without an extra request
    assert images_api.refreshes == []

    await generate(OpenRouterBackend(model="some/model-not-in-the-list"), prompt="x")
    # an unlisted one is looked up in a refreshed list first
    assert images_api.refreshes == [True]

    assert routed == ["google/gemini-3-pro-image-preview", "some/model-not-in-the-list"]
    assert images_api.requests == []


async def test_an_image_only_model_the_loaded_list_misses_uses_the_image_api(
    images_api,
):
    images_api.released_later = {
        "new/image-model": openrouter_client.ImageModel(
            id="new/image-model", output_modalities=["image"]
        )
    }

    await generate(OpenRouterBackend(model="new/image-model"), prompt="x")

    assert images_api.refreshes == [True]
    [sent] = images_api.requests
    assert sent["json"]["model"] == "new/image-model"


@pytest.mark.parametrize(
    "model, image_format, aspect_ratio",
    [
        ("black-forest-labs/flux.2-pro", FORMAT_TYPE.LANDSCAPE, "16:9"),
        ("black-forest-labs/flux.2-pro", FORMAT_TYPE.PORTRAIT, "9:16"),
        ("openai/gpt-image-1", FORMAT_TYPE.LANDSCAPE, "3:2"),
        ("openai/gpt-image-1", FORMAT_TYPE.PORTRAIT, "2:3"),
        ("openai/gpt-image-1", FORMAT_TYPE.SQUARE, "1:1"),
    ],
)
async def test_the_aspect_ratio_is_one_the_model_lists(
    images_api, model, image_format, aspect_ratio
):
    await generate(OpenRouterBackend(model=model), prompt="x", format=image_format)

    assert images_api.requests[0]["json"]["aspect_ratio"] == aspect_ratio


async def test_png_is_requested_when_the_model_lists_it(images_api):
    images_api.response = FakeImagesResponse(
        200, image_api_payload(image_bytes("PNG"), "image/png")
    )

    _, response = await generate(
        OpenRouterBackend(model="inclusionai/ming-image-0.1-design"), prompt="x"
    )

    sent = images_api.requests[0]["json"]
    assert sent["output_format"] == "png"
    assert "aspect_ratio" not in sent
    # a PNG answer is kept byte for byte
    assert response.generated == image_bytes("PNG")


async def test_a_jpeg_image_api_answer_is_stored_as_png(images_api):
    images_api.response = FakeImagesResponse(
        200, image_api_payload(image_bytes("JPEG"), "image/jpeg")
    )

    _, response = await generate(OpenRouterBackend(model="meta/muse-image"), prompt="x")

    with Image.open(io.BytesIO(response.generated)) as image:
        assert image.format == "PNG"


async def test_an_edit_sends_the_references_and_the_provider_routing(
    images_api, monkeypatch
):
    monkeypatch.setattr(
        GenerationRequest,
        "reference_bytes",
        property(lambda self: [b"ref-1", b"", b"ref-2", b"ref-3"]),
    )
    backend = OpenRouterBackend(
        model="meta/muse-image",
        max_references_config=2,
        provider_only=["Meta"],
        provider_ignore=["Novita"],
    )

    await generate(backend, prompt="make it watercolor", gen_type=GEN_TYPE.IMAGE_EDIT)

    sent = images_api.requests[0]["json"]
    assert sent["prompt"] == "make it watercolor"
    assert sent["input_references"] == [
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{base64.b64encode(ref).decode()}"
            },
        }
        for ref in (b"ref-1", b"ref-2")
    ]
    assert sent["provider"] == {"only": ["Meta"], "ignore": ["Novita"]}


async def test_an_edit_without_references_is_refused(images_api):
    with pytest.raises(ValueError, match="at least one reference image"):
        await generate(
            OpenRouterBackend(model="meta/muse-image"),
            prompt="x",
            gen_type=GEN_TYPE.IMAGE_EDIT,
        )

    assert images_api.requests == []


async def test_an_openrouter_error_carries_the_status_and_the_message(images_api):
    images_api.response = FakeImagesResponse(
        400,
        {
            "error": {
                "message": "Novita does not honor `aspect_ratio` on the Ming image models",
                "code": 400,
            }
        },
    )

    with pytest.raises(ValueError, match=r"HTTP 400\): Novita does not honor"):
        await generate(
            OpenRouterBackend(model="inclusionai/ming-image-0.1-design"), prompt="x"
        )


async def test_an_error_without_a_json_body_carries_the_text(images_api):
    images_api.response = FakeImagesResponse(502, None, text="Bad Gateway")

    with pytest.raises(ValueError, match=r"HTTP 502\): Bad Gateway"):
        await generate(OpenRouterBackend(model="meta/muse-image"), prompt="x")


async def test_an_answer_without_an_image_is_an_error(images_api):
    images_api.response = FakeImagesResponse(200, {"data": []})

    with pytest.raises(ValueError, match="missing image data"):
        await generate(OpenRouterBackend(model="meta/muse-image"), prompt="x")


async def test_an_image_talemate_cannot_read_names_its_media_type(images_api):
    images_api.response = FakeImagesResponse(
        200,
        image_api_payload(
            b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml"
        ),
    )

    with pytest.raises(ValueError, match=r"cannot read \(image/svg\+xml\)"):
        await generate(OpenRouterBackend(model="meta/muse-image"), prompt="x")


@pytest.mark.parametrize(
    "target, listed, nearest",
    [
        ("16:9", ["1:1", "16:9", "9:16"], "16:9"),
        ("16:9", ["1:1", "3:2", "2:3", "auto"], "3:2"),
        ("9:16", ["1:1", "3:2", "2:3", "auto"], "2:3"),
        ("9:16", ["9:19.5", "19.5:9", "1:1"], "9:19.5"),
        ("16:9", ["auto"], None),
        ("16:9", [], None),
    ],
)
def test_nearest_aspect_ratio(target, listed, nearest):
    assert nearest_aspect_ratio(target, listed) == nearest


# --- listed reference range and SVG output (#734 review) --------------------


def references(*refs):
    return property(lambda self: list(refs))


async def test_an_svg_only_model_is_refused_before_any_request(images_api):
    with pytest.raises(ValueError, match="only makes SVG images"):
        await generate(OpenRouterBackend(model="recraft/recraft-v4-vector"), prompt="x")

    assert images_api.requests == []


async def test_an_edit_with_a_model_that_takes_no_references_is_refused(
    images_api, monkeypatch
):
    monkeypatch.setattr(GenerationRequest, "reference_bytes", references(b"ref-1"))

    with pytest.raises(ValueError, match="does not accept reference images"):
        await generate(
            OpenRouterBackend(model="inclusionai/ming-image-0.1-design"),
            prompt="x",
            gen_type=GEN_TYPE.IMAGE_EDIT,
        )

    assert images_api.requests == []


async def test_text_to_image_with_a_model_that_needs_references_is_refused(
    images_api,
):
    with pytest.raises(ValueError, match="needs at least 1 reference image"):
        await generate(OpenRouterBackend(model="recraft/recraft-v4-styles"), prompt="x")

    assert images_api.requests == []


async def test_a_model_that_needs_references_edits(images_api, monkeypatch):
    monkeypatch.setattr(
        GenerationRequest, "reference_bytes", references(b"ref-1", b"ref-2")
    )

    await generate(
        OpenRouterBackend(model="recraft/recraft-v4-styles", max_references_config=2),
        prompt="x",
        gen_type=GEN_TYPE.IMAGE_EDIT,
    )

    assert len(images_api.requests[0]["json"]["input_references"]) == 2


async def test_references_stop_at_the_listed_maximum(images_api, monkeypatch):
    monkeypatch.setattr(
        GenerationRequest, "reference_bytes", references(b"ref-1", b"ref-2", b"ref-3")
    )

    await generate(
        OpenRouterBackend(model="krea/krea-2-medium", max_references_config=3),
        prompt="x",
        gen_type=GEN_TYPE.IMAGE_EDIT,
    )

    assert len(images_api.requests[0]["json"]["input_references"]) == 1


async def test_a_transport_error_names_its_type(images_api):
    # an httpx timeout carries an empty str()
    images_api.response = httpx.ReadTimeout("")

    with pytest.raises(
        ValueError, match=r"^OpenRouter image request failed: ReadTimeout$"
    ):
        await generate(OpenRouterBackend(model="meta/muse-image"), prompt="x")


# --- the chat path of the models that also write text -----------------------


class FakeChatCompletions:
    def __init__(self):
        self.calls = []
        self.answer_url = data_url(image_bytes("PNG"))

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        message = SimpleNamespace(images=[{"image_url": {"url": self.answer_url}}])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


@pytest.fixture
def chat_completions(monkeypatch, images_api):
    completions = FakeChatCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    monkeypatch.setattr(OpenRouterBackend, "_make_client", lambda self: client)
    return completions


@pytest.fixture
def chat_api(chat_completions):
    return chat_completions.calls


def data_url(image_bytes: bytes, media_type: str = "image/png") -> str:
    return f"data:{media_type};base64,{base64.b64encode(image_bytes).decode()}"


async def test_the_gemini_chat_request_for_text_to_image(chat_api, images_api):
    backend = OpenRouterBackend(
        model="google/gemini-3-pro-image-preview", provider_only=["Google AI Studio"]
    )

    await generate(backend, prompt="a lighthouse at dusk", format=FORMAT_TYPE.LANDSCAPE)

    assert chat_api == [
        {
            "model": "google/gemini-3-pro-image-preview",
            "messages": [{"role": "user", "content": "a lighthouse at dusk"}],
            "extra_body": {
                "modalities": ["image", "text"],
                "image_config": {"aspect_ratio": "16:9"},
                "provider": {"only": ["Google AI Studio"]},
            },
            "timeout": 42,
        }
    ]
    assert images_api.requests == []


async def test_the_gemini_chat_request_for_an_edit(chat_api, images_api, monkeypatch):
    monkeypatch.setattr(
        GenerationRequest, "reference_bytes", references(b"ref-1", b"ref-2", b"ref-3")
    )
    backend = OpenRouterBackend(
        model="google/gemini-3-pro-image-preview", max_references_config=2
    )

    await generate(
        backend,
        prompt="make it a watercolor",
        gen_type=GEN_TYPE.IMAGE_EDIT,
        format=FORMAT_TYPE.PORTRAIT,
    )

    assert chat_api == [
        {
            "model": "google/gemini-3-pro-image-preview",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "make it a watercolor"},
                        {"type": "image_url", "image_url": {"url": data_url(b"ref-1")}},
                        {"type": "image_url", "image_url": {"url": data_url(b"ref-2")}},
                    ],
                }
            ],
            "extra_body": {
                "modalities": ["image", "text"],
                "image_config": {"aspect_ratio": "9:16"},
            },
            "timeout": 42,
        }
    ]
    assert images_api.requests == []


CHAT_GEN_TYPES = [GEN_TYPE.TEXT_TO_IMAGE, GEN_TYPE.IMAGE_EDIT]


@pytest.mark.parametrize("gen_type", CHAT_GEN_TYPES)
async def test_a_jpeg_chat_answer_is_stored_as_png(
    chat_completions, monkeypatch, gen_type
):
    # google/gemini-3.1-flash-lite-image answers with JPEG on the chat path
    monkeypatch.setattr(GenerationRequest, "reference_bytes", references(b"ref-1"))
    chat_completions.answer_url = data_url(
        image_bytes("JPEG", size=(80, 48)), "image/jpeg"
    )

    request, response = await generate(
        OpenRouterBackend(model="google/gemini-3-pro-image-preview"),
        prompt="x",
        gen_type=gen_type,
    )

    with Image.open(io.BytesIO(response.generated)) as image:
        assert image.format == "PNG"
        assert image.size == (80, 48)
    assert (request.resolution.width, request.resolution.height) == (80, 48)


@pytest.mark.parametrize("gen_type", CHAT_GEN_TYPES)
async def test_a_png_chat_answer_is_kept_byte_for_byte(
    chat_completions, monkeypatch, gen_type
):
    monkeypatch.setattr(GenerationRequest, "reference_bytes", references(b"ref-1"))
    chat_completions.answer_url = data_url(image_bytes("PNG"))

    _, response = await generate(
        OpenRouterBackend(model="google/gemini-3-pro-image-preview"),
        prompt="x",
        gen_type=gen_type,
    )

    assert response.generated == image_bytes("PNG")


async def test_a_chat_answer_talemate_cannot_read_is_an_error(chat_completions):
    chat_completions.answer_url = data_url(b"not an image")

    with pytest.raises(ValueError, match=r"cannot read \(unknown format\)"):
        await generate(
            OpenRouterBackend(model="google/gemini-3-pro-image-preview"), prompt="x"
        )


@pytest.mark.parametrize(
    "model, configured, offered",
    [
        ("krea/krea-2-medium", 3, 1),  # listed maximum 1
        ("black-forest-labs/flux.2-pro", 3, 3),  # listed maximum 8
        ("meta/muse-image", 3, 3),  # no listed range
        ("inclusionai/ming-image-0.1-design", 2, 2),  # takes none: never 0
        ("google/gemini-3-pro-image-preview", 3, 3),  # chat path, not capped
        ("some/model-not-in-the-list", 2, 2),
    ],
)
def test_the_offered_references_follow_the_listed_maximum(
    openrouter_lists, model, configured, offered
):
    backend = OpenRouterBackend(model=model, max_references_config=configured)

    assert backend.max_references == offered
