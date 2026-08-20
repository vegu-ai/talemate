"""The status probe of clients that read their model from an
OpenAI-compatible `/models` listing (issue #338).

The sweep that schedules the probe and the bound it runs under live in
`talemate.instance` and are covered in `tests/test_instance.py`.
"""

from __future__ import annotations

import pytest

import talemate.config.state as config_state
from talemate.client.llamacpp import LlamaCppClient
from talemate.client.lmstudio import LMStudioClient
from talemate.config.schema import Client as ClientConfig


class _FakeModels:
    def __init__(self, owner: "_FakeOpenAIClient", ids: list[str]):
        self.owner = owner
        self.ids = ids

    async def list(self, timeout=None):
        self.owner.list_timeout = timeout

        class _Model:
            def __init__(self, id_: str):
                self.id = id_

        class _Page:
            def __init__(self, ids):
                self.data = [_Model(i) for i in ids]

        return _Page(self.ids)


class _FakeOpenAIClient:
    """Stands in for AsyncOpenAI: records the options a probe asks for and
    whether the probe closed it."""

    def __init__(self, ids: list[str] | None = None):
        self.ids = ids if ids is not None else ["/models/some-model.gguf"]
        self.max_retries = None
        self.list_timeout = None
        self.closed = False

    def with_options(self, **kwargs):
        self.max_retries = kwargs.get("max_retries")
        return self

    @property
    def models(self):
        return _FakeModels(self, self.ids)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self.closed = True
        return False


def _llamacpp(name: str) -> LlamaCppClient:
    config_state.CONFIG.clients[name] = ClientConfig(
        type="llamacpp", name=name, api_url="http://localhost:8080"
    )
    return LlamaCppClient(name=name)


def _lmstudio(name: str) -> LMStudioClient:
    config_state.CONFIG.clients[name] = ClientConfig(
        type="lmstudio", name=name, api_url="http://localhost:1234"
    )
    return LMStudioClient(name=name)


class TestProbeUsesOneClosedAttempt:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("factory", [_llamacpp, _lmstudio])
    async def test_probe_makes_one_attempt_and_closes_its_client(
        self, cfg_isolation, factory
    ):
        client = factory("probe1")
        fake = _FakeOpenAIClient()
        client.make_client = lambda: fake

        model_name = await client.get_model_name()

        assert model_name == "some-model.gguf"
        assert fake.max_retries == 0
        assert fake.list_timeout == client.status_request_timeout
        assert fake.closed is True

    @pytest.mark.asyncio
    async def test_probe_closes_its_client_when_the_listing_fails(self, cfg_isolation):
        client = _llamacpp("probe2")

        class _FailingClient(_FakeOpenAIClient):
            @property
            def models(self):
                raise RuntimeError("connection error")

        fake = _FailingClient()
        client.make_client = lambda: fake

        with pytest.raises(RuntimeError):
            await client.get_model_name()

        assert fake.closed is True

    @pytest.mark.asyncio
    async def test_empty_listing_yields_no_model_name(self, cfg_isolation):
        client = _llamacpp("probe3")
        fake = _FakeOpenAIClient(ids=[])
        client.make_client = lambda: fake

        assert await client.get_model_name() is None

    @pytest.mark.asyncio
    async def test_windows_style_model_id_is_reduced_to_its_basename(
        self, cfg_isolation
    ):
        client = _llamacpp("probe4")
        fake = _FakeOpenAIClient(ids=["C:\\models\\gguf\\some-model.gguf"])
        client.make_client = lambda: fake

        assert await client.get_model_name() == "some-model.gguf"

    @pytest.mark.asyncio
    async def test_no_api_url_skips_the_probe(self, cfg_isolation):
        config_state.CONFIG.clients["probe5"] = ClientConfig(
            type="llamacpp", name="probe5", api_url=""
        )
        client = LlamaCppClient(name="probe5")

        def _unreachable():
            raise AssertionError("the probe must not build a client")

        client.make_client = _unreachable

        assert await client.get_model_name() is None
