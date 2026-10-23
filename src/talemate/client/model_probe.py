"""Model discovery for clients that talk to an OpenAI-compatible endpoint."""

__all__ = ["OpenAIModelListProbeMixin"]


class OpenAIModelListProbeMixin:
    """Reads the loaded model's name from an OpenAI-compatible `/models`
    listing. Expects `make_client()` to return an `AsyncOpenAI` for the
    endpoint."""

    async def get_model_name(self) -> str | None:
        return await self.probe_model_name()

    async def probe_model_name(self) -> str | None:
        # single attempt: the status sweep repeats every 3s, and the SDK's two
        # extra retries would stretch one probe of a dead endpoint to ~7s
        async with self.make_client() as client:
            models = await client.with_options(max_retries=0).models.list(
                timeout=self.status_request_timeout
            )
        try:
            model_name = models.data[0].id
        except IndexError:
            return None

        if not model_name:
            return model_name

        # the id can be a file path from either platform; keep the basename
        return model_name.replace("\\", "/").split("/")[-1]
