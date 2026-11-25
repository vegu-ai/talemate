"""
The Visualizer's Venice backend: its settings, the API key lookup, and the
requests it sends for text-to-image and image editing.
"""

import base64
from unittest import mock

import httpx
import pytest

import talemate.agents.visual.backends.venice_image as venice
from talemate.agents.visual.agent import VisualAgent
from talemate.agents.visual.backends import BackendStatusType
from talemate.agents.visual.schema import (
    FORMAT_TYPE,
    GEN_TYPE,
    GenerationRequest,
    GenerationResponse,
    Resolution,
)

VENICE_ACTIONS = ("venice_image_create", "venice_image_edit")
IMAGE = b"\x89PNG-bytes"


@pytest.fixture
def visual_agent():
    return VisualAgent()


@pytest.fixture
def backend(monkeypatch):
    monkeypatch.delenv("VENICE_API_KEY", raising=False)
    monkeypatch.setattr(
        venice, "get_agent", lambda _name: mock.Mock(generate_timeout=30)
    )
    monkeypatch.setattr(venice, "_ASPECT_RATIO_MODELS", set())
    return venice.Backend(
        model="m", api_key="secret", gen_type=GEN_TYPE.TEXT_TO_IMAGE
    )


def request(gen_type=GEN_TYPE.TEXT_TO_IMAGE, **kwargs):
    return GenerationRequest(
        prompt="a lighthouse",
        gen_type=gen_type,
        resolution=Resolution(width=1216, height=832),
        **kwargs,
    )


def fake_http(monkeypatch, *responses):
    """Replace httpx.AsyncClient; returns the list of recorded requests."""
    calls = []
    queue = list(responses)

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, **kwargs):
            calls.append((url, kwargs))
            return queue.pop(0)

        async def get(self, url, **kwargs):
            calls.append((url, kwargs))
            return queue.pop(0)

    monkeypatch.setattr(venice.httpx, "AsyncClient", Client)
    return calls


def reply(status=200, **kwargs):
    return httpx.Response(status, request=httpx.Request("POST", "http://x"), **kwargs)


def test_api_key_field_is_masked_and_not_scene_overridable(visual_agent):
    for action_name in VENICE_ACTIONS:
        field = visual_agent.actions[action_name].config["api_key"]
        assert field.type == "password"
        assert field.scene_overridable is False


def test_default_models(visual_agent):
    config = visual_agent.actions
    assert config["venice_image_create"].config["model"].value == "venice-sd35"
    assert config["venice_image_edit"].config["model"].value == "firered-image-edit"


def test_api_key_falls_back_to_environment(monkeypatch):
    monkeypatch.setenv("VENICE_API_KEY", "from-env")
    assert venice._api_key(None) == "from-env"
    assert venice._api_key("from-setting") == "from-setting"


async def test_connection_reports_missing_key(backend, monkeypatch):
    backend.api_key = None
    status = await backend.test_connection()
    assert status.type == BackendStatusType.ERROR
    assert "API key" in status.message


async def test_connection_ok_sends_bearer_key(backend, monkeypatch):
    calls = fake_http(monkeypatch, reply(json={"data": []}))
    status = await backend.test_connection()
    assert status.type == BackendStatusType.OK
    url, kwargs = calls[0]
    assert url.endswith("/models")
    assert kwargs["headers"] == {"Authorization": "Bearer secret"}


async def test_generate_decodes_base64_image(backend, monkeypatch):
    encoded = base64.b64encode(IMAGE).decode()
    calls = fake_http(monkeypatch, reply(json={"images": [encoded]}))

    response = await backend.generate(request(), GenerationResponse())

    assert response.generated == IMAGE
    url, kwargs = calls[0]
    assert url.endswith("/image/generate")
    assert kwargs["json"]["width"] == 1216
    assert kwargs["json"]["safe_mode"] is True


async def test_low_moderation_turns_safe_mode_off(backend, monkeypatch):
    backend.moderation = "low"
    encoded = base64.b64encode(IMAGE).decode()
    calls = fake_http(monkeypatch, reply(json={"images": [encoded]}))

    await backend.generate(request(), GenerationResponse())

    assert calls[0][1]["json"]["safe_mode"] is False


async def test_generate_retries_with_aspect_ratio_when_size_is_rejected(
    backend, monkeypatch
):
    encoded = base64.b64encode(IMAGE).decode()
    calls = fake_http(
        monkeypatch,
        reply(400, text="use aspect_ratio instead"),
        reply(json={"images": [encoded]}),
    )

    req = request()
    req.format = FORMAT_TYPE.LANDSCAPE
    response = await backend.generate(req, GenerationResponse())

    assert response.generated == IMAGE
    retry = calls[1][1]["json"]
    assert "width" not in retry and "height" not in retry
    assert retry["aspect_ratio"] == "3:2"
    assert "m" in venice._ASPECT_RATIO_MODELS


async def test_generate_error_includes_status_and_body(backend, monkeypatch):
    fake_http(monkeypatch, reply(500, text="boom"))
    with pytest.raises(ValueError, match="500.*boom"):
        await backend.generate(request(), GenerationResponse())


async def test_generate_without_images_raises(backend, monkeypatch):
    fake_http(monkeypatch, reply(json={"images": []}))
    with pytest.raises(ValueError, match="no images"):
        await backend.generate(request(), GenerationResponse())


async def test_edit_posts_reference_image_and_returns_binary(backend, monkeypatch):
    calls = fake_http(monkeypatch, reply(content=IMAGE))

    response = await backend.generate(
        request(GEN_TYPE.IMAGE_EDIT, reference_bytes=[IMAGE]),
        GenerationResponse(),
    )

    assert response.generated == IMAGE
    url, kwargs = calls[0]
    assert url.endswith("/image/edit")
    assert kwargs["files"]["image"][1] == IMAGE
    assert kwargs["data"]["safe_mode"] == "true"


async def test_edit_requires_a_reference_image(backend):
    with pytest.raises(ValueError, match="reference image"):
        await backend.generate(request(GEN_TYPE.IMAGE_EDIT), GenerationResponse())


async def test_unsupported_generation_type_is_rejected(backend):
    with pytest.raises(ValueError, match="only supports"):
        await backend.generate(
            request(GEN_TYPE.IMAGE_ANALYSIS), GenerationResponse()
        )
