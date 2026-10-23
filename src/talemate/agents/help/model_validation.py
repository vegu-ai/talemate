from urllib.parse import quote

import httpx
import pydantic

from talemate.client import openrouter


class ModelCapabilities(pydantic.BaseModel):
    input_modalities: list[str] | None = None
    output_modalities: list[str] | None = None


class ModelLookup(pydantic.BaseModel):
    id: str
    architecture: ModelCapabilities


async def validate_openrouter_model(model_id: str) -> dict:
    if (
        not isinstance(model_id, str)
        or len(model_id) > 256
        or len(model_id.split("/")) != 2
        or any(part in ("", ".", "..") for part in model_id.split("/"))
        or any(char.isspace() for char in model_id)
    ):
        return {
            "error": "Provide the exact OpenRouter model id chosen by the user (author/model)."
        }

    result = {"model_id": model_id, "exists": None}
    image_models = await openrouter.fetch_available_image_models()
    image_model = image_models.get(model_id)
    if image_model is not None:
        return {
            **result,
            "exists": True,
            "input_modalities": image_model.input_modalities,
            "output_modalities": image_model.output_modalities,
            "reference_images": {
                "min": image_model.min_references,
                "max": image_model.max_references,
            },
            "output_formats": image_model.output_formats,
        }

    path = "/".join(quote(part, safe="") for part in model_id.split("/"))
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{openrouter.MODELS_URL}/{path}/endpoints", timeout=10.0
            )
        if response.status_code == 404:
            if openrouter.IMAGE_MODELS_FETCH.fetched:
                return {**result, "exists": False}
            return {
                **result,
                "error": "Image model lookup is unavailable; existence could not be verified.",
            }
        response.raise_for_status()
        model = ModelLookup.model_validate(response.json()["data"])
        if model.id != model_id:
            return {
                **result,
                "error": "OpenRouter returned a different model id; existence could not be verified.",
            }
        return {**result, "exists": True, **model.architecture.model_dump()}
    except httpx.HTTPStatusError as exc:
        return {
            **result,
            "error": f"OpenRouter model lookup failed (HTTP {exc.response.status_code}).",
        }
    except (httpx.RequestError, ValueError, KeyError, TypeError):
        return {
            **result,
            "error": "OpenRouter model lookup is unavailable; try again later.",
        }
