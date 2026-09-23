from unittest.mock import AsyncMock

import httpx
import pytest

from talemate.agents.help import model_validation
from talemate.client import openrouter


@pytest.fixture
def lookup_http(monkeypatch):
    monkeypatch.setattr(
        openrouter, "fetch_available_image_models", AsyncMock(return_value={})
    )
    monkeypatch.setattr(openrouter, "IMAGE_MODELS_FETCH", openrouter.ListFetch())
    openrouter.IMAGE_MODELS_FETCH.fetched = True
    real_client = httpx.AsyncClient
    calls = []

    def install(status=200, body=None, error=None):
        def respond(request):
            calls.append(request)
            if error:
                raise error
            return httpx.Response(status, json=body)

        monkeypatch.setattr(
            model_validation.httpx,
            "AsyncClient",
            lambda: real_client(transport=httpx.MockTransport(respond)),
        )
        return calls

    return install


@pytest.mark.asyncio
async def test_exact_model_metadata_excludes_other_api_fields(lookup_http):
    calls = lookup_http(
        body={
            "data": {
                "id": "user/chosen-model",
                "architecture": {
                    "input_modalities": ["text", "image"],
                    "output_modalities": ["text"],
                },
                "description": "untrusted description",
                "endpoints": [
                    {"model_id": "other/model", "provider_name": "other-provider"}
                ],
            }
        }
    )
    result = await model_validation.validate_openrouter_model("user/chosen-model")
    assert result == {
        "model_id": "user/chosen-model",
        "exists": True,
        "input_modalities": ["text", "image"],
        "output_modalities": ["text"],
    }
    assert len(calls) == 1
    assert str(calls[0].url) == f"{openrouter.MODELS_URL}/user/chosen-model/endpoints"
    assert "authorization" not in calls[0].headers


@pytest.mark.asyncio
async def test_image_model_uses_loaded_catalogue(lookup_http, monkeypatch):
    calls = lookup_http()
    image = openrouter.ImageModel.from_entry(
        {
            "id": "user/chosen-image",
            "architecture": {
                "input_modalities": ["text", "image"],
                "output_modalities": ["image"],
            },
            "supported_parameters": {
                "input_references": {"type": "range", "min": 0, "max": 4},
                "output_format": {"type": "enum", "values": ["png"]},
            },
        }
    )
    monkeypatch.setattr(
        openrouter,
        "fetch_available_image_models",
        AsyncMock(return_value={image.id: image, "other/model": image}),
    )
    result = await model_validation.validate_openrouter_model(image.id)
    assert result == {
        "model_id": image.id,
        "exists": True,
        "input_modalities": ["text", "image"],
        "output_modalities": ["image"],
        "reference_images": {"min": 0, "max": 4},
        "output_formats": ["png"],
    }
    assert calls == []


@pytest.mark.asyncio
async def test_unknown_capabilities_are_not_inferred(lookup_http):
    lookup_http(body={"data": {"id": "user/model", "architecture": {}}})
    result = await model_validation.validate_openrouter_model("user/model")
    assert result["exists"] is True
    assert result["input_modalities"] is None
    assert result["output_modalities"] is None


@pytest.mark.parametrize("images_loaded,exists", [(True, False), (False, None)])
@pytest.mark.asyncio
async def test_missing_model_requires_successful_image_lookup(
    lookup_http, images_loaded, exists
):
    lookup_http(status=404)
    openrouter.IMAGE_MODELS_FETCH.fetched = images_loaded
    result = await model_validation.validate_openrouter_model("user/missing")
    assert result["exists"] is exists


@pytest.mark.parametrize("status", [401, 403, 429, 500])
@pytest.mark.asyncio
async def test_http_errors_report_unknown_without_echoing_response(lookup_http, status):
    lookup_http(status=status, body={"error": "private response content"})
    result = await model_validation.validate_openrouter_model("user/model")
    assert result["exists"] is None
    assert str(status) in result["error"]
    assert "private response" not in str(result)


@pytest.mark.asyncio
async def test_timeout_reports_unknown(lookup_http):
    lookup_http(error=httpx.ReadTimeout("private exception content"))
    result = await model_validation.validate_openrouter_model("user/model")
    assert result["exists"] is None
    assert "private exception" not in str(result)


@pytest.mark.parametrize(
    "body", [{}, {"data": []}, {"data": {"id": "other/model", "architecture": {}}}]
)
@pytest.mark.asyncio
async def test_invalid_metadata_is_not_a_positive_validation(lookup_http, body):
    lookup_http(body=body)
    result = await model_validation.validate_openrouter_model("user/model")
    assert result["exists"] is None
    assert "error" in result


@pytest.mark.parametrize(
    "model_id",
    [
        "",
        "model",
        "../model",
        "user/..",
        "user/a/b",
        "user/model name",
        None,
        "a" * 300 + "/b",
    ],
)
@pytest.mark.asyncio
async def test_malformed_id_makes_no_metadata_request(lookup_http, model_id):
    calls = lookup_http()
    result = await model_validation.validate_openrouter_model(model_id)
    assert "error" in result
    assert calls == []
    openrouter.fetch_available_image_models.assert_not_awaited()
