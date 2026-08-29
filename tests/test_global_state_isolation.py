"""Regression tests for the conftest fixtures that keep process-wide state
from leaking between tests.

The suite runs distributed, so test order is no longer fixed — and with
``--dist worksteal`` two tests from this very file can land on different
workers. So none of these tests may depend on another having run first: each
drives the fixture's own generator (``__wrapped__`` is the undecorated
function) through setup and teardown, and checks the restore directly.
"""

import sys

import pytest

import talemate.agents.tts.voice_library as voice_library
import talemate.emit.async_signals as async_signals
import talemate.instance as instance
import talemate.server.agent_config as agent_config
from talemate.agents.tts.schema import Voice

import conftest
from conftest import bootstrap_engine


def run_fixture(fixture):
    """Return a context manager that drives a generator fixture by hand."""

    class _Driver:
        def __enter__(self):
            self.gen = fixture.__wrapped__()
            return next(self.gen)

        def __exit__(self, *exc):
            with pytest.raises(StopIteration):
                next(self.gen)
            return False

    return _Driver()


class TestAgentsRegistryIdentity:
    def test_modules_that_imported_agents_by_name_see_the_same_dict(self):
        """``instance.AGENTS`` must never be rebound.

        ``talemate/server/agent_config.py`` does ``from talemate.instance
        import AGENTS``, binding the dict object itself. Restoring the registry
        by assigning a *new* dict leaves that module pointing at the old one,
        and it silently stops seeing agents anything else registers — the
        original defect this suite tripped over.
        """
        assert agent_config.AGENTS is instance.AGENTS

    def test_registry_writes_are_visible_through_the_by_name_import(self):
        sentinel = object()
        instance.AGENTS["isolation-probe"] = sentinel
        try:
            assert agent_config.AGENTS.get("isolation-probe") is sentinel
        finally:
            instance.AGENTS.pop("isolation-probe", None)


class TestRestoreGlobalRegistries:
    """``bootstrap_engine()`` writes to two process-wide registries and
    restores neither; the autouse fixture is what puts them back."""

    def test_bootstrap_engine_agents_are_rolled_back(self):
        with run_fixture(conftest.restore_global_registries):
            bootstrap_engine()
            assert "director" in instance.AGENTS

        assert "director" not in instance.AGENTS

    def test_agents_registry_is_restored_in_place_not_rebound(self):
        before = instance.AGENTS
        with run_fixture(conftest.restore_global_registries):
            bootstrap_engine()

        assert instance.AGENTS is before
        assert agent_config.AGENTS is instance.AGENTS

    def test_voice_library_rebind_is_rolled_back(self):
        before = voice_library.VOICE_LIBRARY
        probe = Voice(label="Probe", provider="probe", provider_id="p1")

        with run_fixture(conftest.restore_global_registries):
            voice_library.VOICE_LIBRARY = voice_library.VoiceLibrary(
                voices={probe.id: probe}
            )
            assert probe.id in voice_library.VOICE_LIBRARY.voices

        assert voice_library.VOICE_LIBRARY is before


class TestSignalSnapshotInvariant:
    """``restore_signal_receivers`` restores to a snapshot taken at test setup,
    so a module that connects at *import* time and is first imported inside a
    test body has its receiver wiped at that test's teardown — permanently, and
    silently, since module-level code never runs twice."""

    # Every module in `src/` with a module-level `.connect(`. Add to this when
    # a new one appears; the failure it guards against is otherwise invisible.
    CONNECTING_MODULES = {
        "talemate.instance",
        "talemate.scene_assets",
        "talemate.client.openrouter",
        "talemate.client.pi_bridge",
    }

    def test_import_time_connectors_are_imported_before_tests_run(self):
        missing = self.CONNECTING_MODULES - sys.modules.keys()
        assert not missing, (
            f"{sorted(missing)} connect to signals at import time but are not "
            "imported by tests/conftest.py. Whichever test imports one first "
            "will have its receiver discarded at teardown."
        )


class TestRestoreSignalReceivers:
    def test_receiver_connected_during_a_test_is_disconnected(self):
        signal = async_signals.get("config.changed")

        async def handler(emission):
            pass

        with run_fixture(conftest.restore_signal_receivers):
            signal.connect(handler)
            assert handler in signal.receivers

        assert handler not in signal.receivers

    def test_import_time_receivers_are_preserved(self):
        """Restoring to a snapshot must keep receivers connected at module
        import — wiping those would disable real application behaviour for the
        rest of the worker's session, silently."""
        signal = async_signals.get("config.changed")

        with run_fixture(conftest.restore_signal_receivers):
            pass

        assert instance.on_config_changed in signal.receivers

    def test_receiver_list_identity_is_preserved(self):
        """``AsyncSignal.receivers`` is handed out by reference, so the restore
        has to mutate the list rather than rebind it."""
        signal = async_signals.get("config.changed")
        receivers = signal.receivers

        with run_fixture(conftest.restore_signal_receivers):
            pass

        assert signal.receivers is receivers

    def test_signal_registered_during_a_test_is_left_with_no_receivers(self):
        with run_fixture(conftest.restore_signal_receivers):
            async_signals.register("isolation.probe.signal")
            signal = async_signals.get("isolation.probe.signal")

            async def handler(emission):
                pass

            signal.connect(handler)
            assert signal.receivers == [handler]

        assert async_signals.get("isolation.probe.signal").receivers == []


class TestTemplateDirFixture:
    """The world-state template tests used to share one directory that each of
    them wiped on entry — safe sequentially, a race once distributed."""

    def test_directory_is_empty_and_unique(self, template_dir, tmp_path):
        import os

        assert os.path.isdir(template_dir)
        assert not os.listdir(template_dir)
        assert str(tmp_path) in template_dir
