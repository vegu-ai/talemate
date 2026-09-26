import asyncio
from unittest import mock

import httpx
import pytest

import talemate.agents.visual.backends as backends
from talemate.agents.visual.backends.openrouter import Backend as OpenRouterBackend


@pytest.mark.parametrize("status_type", list(backends.BackendStatusType))
async def test_cancelled_probe_keeps_status_without_callback_error(status_type):
    backend = _ProbeBackend(model="test-model")
    previous = backends.BackendStatus(type=status_type, message="previous status")
    backend.status = previous
    loop = asyncio.get_running_loop()
    errors = []
    old_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda loop, context: errors.append(context))
    try:
        with mock.patch.object(
            _ProbeBackend, "on_status_change", new_callable=mock.AsyncMock
        ) as notify:
            task = await backend.ensure_test_connection_task()
            await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await asyncio.sleep(0)
            assert backend.status is previous
            notify.assert_not_called()
        assert errors == []
    finally:
        loop.set_exception_handler(old_handler)


async def test_failed_probe_still_updates_error_status():
    backend = _ProbeBackend(model="test-model")
    future = asyncio.get_running_loop().create_future()
    future.set_exception(ValueError("probe failed"))
    with mock.patch.object(
        _ProbeBackend, "on_status_change", new_callable=mock.AsyncMock
    ) as notify:
        backend._update_status_from_future(future)
        await asyncio.sleep(0)
        assert backend.status.type == backends.BackendStatusType.ERROR
        assert backend.status.message == "probe failed"
        notify.assert_awaited_once()


def test_openrouter_cache_maxage_is_60():
    # regression: declared without ClassVar this silently resolved to the
    # base value of 1, and the status loop re-probed openrouter every tick
    backend = OpenRouterBackend(model="test-model")
    assert backend._test_conn_cache_maxage == 60


class TestDescribeError:
    def test_returns_message_when_present(self):
        assert backends.describe_error(ValueError("boom")) == "boom"

    def test_falls_back_to_type_name_when_message_empty(self):
        assert backends.describe_error(httpx.ReadTimeout("")) == "ReadTimeout"


class _ProbeBackend(OpenRouterBackend):
    probes: int = 0

    @property
    def status_cache_key(self):
        return "test-probe-backend"

    async def test_connection(self, timeout: int = 5):
        self.probes += 1
        return backends.BackendStatus(type=backends.BackendStatusType.OK)


class TestConnectionCacheBehavior:
    def setup_method(self):
        backends.Backend._test_conn_cache.pop("test-probe-backend", None)

    def teardown_method(self):
        backends.Backend._test_conn_cache.pop("test-probe-backend", None)

    async def test_cached_status_avoids_reprobe_until_expiry(self):
        backend = _ProbeBackend(model="test-model")
        # match the probed status so the done callback sees no change and
        # doesn't spawn on_status_change into the (unregistered) visual agent
        backend.status = backends.BackendStatus(type=backends.BackendStatusType.OK)
        with mock.patch(
            "talemate.agents.visual.backends.random.uniform", return_value=0
        ):
            # first probe populates the cache via the done callback
            task = await backend.ensure_test_connection_task()
            await task
            # second run consults the cache instead of probing
            task = await backend.ensure_test_connection_task()
            await task
            assert backend.probes == 1

            # mid-window the cache is still consulted - this is what pins the
            # 60s maxage; without it the test passes for any maxage > 0
            with mock.patch(
                "talemate.agents.visual.backends.time.time",
                return_value=task.result().timestamp + 30,
            ):
                task = await backend.ensure_test_connection_task()
                await task
            assert backend.probes == 1

            # past the maxage the next run probes again
            with mock.patch(
                "talemate.agents.visual.backends.time.time",
                return_value=task.result().timestamp + 61,
            ):
                task = await backend.ensure_test_connection_task()
                await task
            assert backend.probes == 2


class _KeyChangingProbeBackend(OpenRouterBackend):
    probes: int = 0
    cache_key: str = "test-probe-key-old"

    @property
    def status_cache_key(self):
        return self.cache_key

    async def test_connection(self, timeout: int = 5):
        self.probes += 1
        # stand in for the user replacing the API key while the probe is in
        # flight: the key the verdict belongs to is no longer the current one
        self.cache_key = "test-probe-key-new"
        return backends.BackendStatus(type=backends.BackendStatusType.OK)


class TestCacheKeyChangedDuringProbe:
    keys = ("test-probe-key-old", "test-probe-key-new")

    def setup_method(self):
        for key in self.keys:
            backends.Backend._test_conn_cache.pop(key, None)

    def teardown_method(self):
        for key in self.keys:
            backends.Backend._test_conn_cache.pop(key, None)

    async def test_verdict_is_filed_under_the_probed_key(self):
        backend = _KeyChangingProbeBackend(model="test-model")
        # pre-set to the probed status for the same reason as above
        backend.status = backends.BackendStatus(type=backends.BackendStatusType.OK)
        with mock.patch(
            "talemate.agents.visual.backends.random.uniform", return_value=0
        ):
            task = await backend.ensure_test_connection_task()
            await task

            assert backend.probes == 1
            # the verdict belongs to the credentials the probe read, not to the
            # ones that replaced them mid-probe
            assert "test-probe-key-old" in backends.Backend._test_conn_cache
            assert "test-probe-key-new" not in backends.Backend._test_conn_cache

            # the replacement is probed on its own, and caches from then on -
            # otherwise the three OpenRouter backend instances sharing this
            # cache would be back to probing every status tick
            task = await backend.ensure_test_connection_task()
            await task
            assert backend.probes == 2
            assert "test-probe-key-new" in backends.Backend._test_conn_cache

            task = await backend.ensure_test_connection_task()
            await task
            assert backend.probes == 2


class TestStatusCacheKey:
    def _key(self, api_key):
        config = mock.MagicMock()
        config.openrouter.api_key = api_key
        backend = OpenRouterBackend(model="test-model")
        with mock.patch(
            "talemate.agents.visual.backends.openrouter.get_config",
            return_value=config,
        ):
            return backend.status_cache_key

    def test_no_key_falls_back_to_backend_name(self):
        assert self._key("") == "openrouter"

    def test_same_prefix_keys_do_not_collide(self):
        # openrouter keys share the fixed sk-or-v1- prefix; the cache key
        # must distinguish keys that differ only after it
        key_a = self._key("sk-or-v1-aaaaaaaaaaaaaaaaaaaa")
        key_b = self._key("sk-or-v1-bbbbbbbbbbbbbbbbbbbb")
        assert key_a != key_b

    def test_key_is_stable(self):
        assert self._key("sk-or-v1-aaaaaaaaaaaaaaaaaaaa") == self._key(
            "sk-or-v1-aaaaaaaaaaaaaaaaaaaa"
        )


class TestOpenRouterTestConnection:
    async def test_error_message_not_empty_on_timeout(self):
        backend = OpenRouterBackend(model="test-model")
        config = mock.MagicMock()
        config.openrouter.api_key = "sk-test"

        client = mock.AsyncMock()
        client.__aenter__.return_value = client
        client.get.side_effect = httpx.ReadTimeout("")

        with (
            mock.patch(
                "talemate.agents.visual.backends.openrouter.get_config",
                return_value=config,
            ),
            mock.patch(
                "talemate.agents.visual.backends.openrouter.httpx.AsyncClient",
                return_value=client,
            ),
        ):
            status = await backend.test_connection()

        assert status.type == backends.BackendStatusType.ERROR
        assert status.message == "ReadTimeout"

    async def test_non_200_status_reports_status_code(self):
        backend = OpenRouterBackend(model="test-model")
        config = mock.MagicMock()
        config.openrouter.api_key = "sk-test"

        client = mock.AsyncMock()
        client.__aenter__.return_value = client
        client.get.return_value = mock.MagicMock(status_code=429)

        with (
            mock.patch(
                "talemate.agents.visual.backends.openrouter.get_config",
                return_value=config,
            ),
            mock.patch(
                "talemate.agents.visual.backends.openrouter.httpx.AsyncClient",
                return_value=client,
            ),
        ):
            status = await backend.test_connection()

        assert status.type == backends.BackendStatusType.ERROR
        assert status.message == "API returned status 429"
