"""
Shared pytest fixtures and test infrastructure.

Provides MockClient, MockScene, and bootstrap functions used across
multiple test modules (test_graphs, test_layered_history, etc.).
"""

import contextvars
import os
from collections import deque
from pathlib import Path

import pytest
import yaml

import talemate.agents as agents
import talemate.agents.memory
import talemate.agents.tts.voice_library as voice_library
import talemate.config.state as config_state
import talemate.emit.async_signals as async_signals
import talemate.instance as instance
from talemate.client import ClientBase
from talemate.config.schema import Config
from talemate.tale_mate import Scene

# Root of the repository (where config.example.yaml lives)
_REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Parallel execution (pytest-xdist)
# ---------------------------------------------------------------------------

# Beyond this, extra workers stop paying: each one re-imports talemate (~5s and
# a few hundred MB), so the fixed cost grows while the shared work per worker
# shrinks. Raise it if you have the cores and the RAM to spare.
#
# Capping here rather than with xdist's `--maxprocesses` is deliberate: that
# flag is applied to *any* worker count (xdist/plugin.py:321-323), so putting it
# in addopts would silently clamp an explicit `-n 16` too. This only shapes the
# `auto` default and leaves an explicit `-n` alone.
MAX_TEST_WORKERS = 8


_CGROUP_V2_CPU_MAX = Path("/sys/fs/cgroup/cpu.max")
_CGROUP_V1_CPU_QUOTA = Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
_CGROUP_V1_CPU_PERIOD = Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us")


def _cgroup_cpu_quota() -> float | None:
    """CPU quota this process is allowed, or None when unrestricted.

    Containers routinely expose every host core through ``os.cpu_count()``
    while the cgroup allows a fraction of one. Without this, ``-n auto`` sizes
    the pool from a number the scheduler will never honour.
    """
    try:
        quota, period = _CGROUP_V2_CPU_MAX.read_text().split()
        if quota != "max":
            return int(quota) / int(period)
        return None
    except (OSError, ValueError):
        pass
    try:
        quota = int(_CGROUP_V1_CPU_QUOTA.read_text())
        period = int(_CGROUP_V1_CPU_PERIOD.read_text())
        if quota > 0:
            return quota / period
    except (OSError, ValueError):
        pass
    return None


def _usable_cpus() -> int:
    """CPUs this process can actually run on.

    Affinity and CFS quota are independent restrictions — ``--cpuset-cpus``,
    Kubernetes' static CPU manager, ``taskset`` and Slurm all pin cores without
    setting a quota, while a quota can apply with every core visible. Both have
    to be consulted; ``os.cpu_count()`` alone sees through neither.
    """
    if hasattr(os, "sched_getaffinity"):
        cpus = len(os.sched_getaffinity(0))
    else:
        cpus = os.cpu_count() or 1
    quota = _cgroup_cpu_quota()
    if quota is not None:
        cpus = min(cpus, int(quota))
    return cpus


def pytest_xdist_auto_num_workers(config):
    """Worker count for ``-n auto`` / ``-n logical``.

    xdist's own implementation prefers ``psutil.cpu_count()``, which sees
    neither cgroup quota nor CPU affinity, and cannot return 0. This one does,
    and 0 is meaningful: it makes xdist run in-process, which is the right
    answer on a single usable CPU, where a second interpreter plus per-test IPC
    is pure cost.

    The hookspec is ``firstresult``, and conftest implementations run ahead of
    plugin ones, so returning None here is how xdist's own handling is allowed
    to take over.
    """
    if os.environ.get("PYTEST_XDIST_AUTO_NUM_WORKERS"):
        # xdist's documented override, and only its own implementation reads it.
        return None

    cpus = _usable_cpus()

    # `-n logical` asks for hyperthreads, `-n auto` for physical cores. Without
    # psutil there is no way to tell them apart, so the affinity count (which is
    # logical) stands in for both.
    if config.option.numprocesses != "logical":
        try:
            import psutil
        except ImportError:
            pass
        else:
            physical = psutil.cpu_count(logical=False)
            if physical:
                cpus = min(cpus, physical)

    # Checked after the clamp, not before: a single physical core behind two
    # hyperthreads would otherwise pass this and then be clamped to 1, and one
    # worker pays the whole IPC and startup bill for no parallelism at all.
    if cpus < 2:
        return 0

    return min(cpus, MAX_TEST_WORKERS)


@pytest.fixture(autouse=True, scope="session")
def _use_example_config():
    """Ensure all tests use config.example.yaml instead of the local config.yaml.

    This prevents local configuration from leaking into test results and
    keeps CI and local runs deterministic.
    """
    example_path = _REPO_ROOT / "config.example.yaml"
    with open(example_path, "r") as f:
        yaml_data = yaml.safe_load(f) or {}
    test_config = Config.model_validate(yaml_data)

    original = config_state.CONFIG
    config_state.CONFIG = test_config
    yield
    config_state.CONFIG = original


# ---------------------------------------------------------------------------
# Contextvar-based response queue for MockClient
# ---------------------------------------------------------------------------

client_responses = contextvars.ContextVar("client_responses", default=deque())


class MockClientContext:
    """Async context manager that provides a fresh response queue."""

    async def __aenter__(self):
        try:
            self.client_responses = client_responses.get()
        except LookupError:
            _client_responses = deque()
            self.token = client_responses.set(_client_responses)
            self.client_responses = _client_responses

        return self.client_responses

    async def __aexit__(self, exc_type, exc_value, traceback):
        if hasattr(self, "token"):
            client_responses.reset(self.token)


# ---------------------------------------------------------------------------
# Async signal helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def restore_signal_receivers():
    """Undo signal connections a test leaves behind.

    ``async_signals.handlers`` is process-wide, and agents connect to it in
    their constructor (``MemoryAgent.__init__`` connects ``config.changed``),
    so anything that instantiates agents — ``bootstrap_engine()`` below, most
    of all — permanently attaches a receiver bound to a throwaway agent. Later
    tests then dispatch into dead objects: emitting ``config.changed`` after a
    bootstrap used to raise ``AttributeError`` inside ``MockMemoryAgent``.

    Snapshotting per test keeps that from leaking, and keeps test order from
    deciding which receivers are attached.

    The invariant this rests on: **any module that connects at import time must
    already be imported when the first snapshot is taken** — module-level code
    never runs twice, so a receiver connected by a module first imported inside
    a test body is wiped at that test's teardown and silently gone for the rest
    of the worker's session. Every such module today (``talemate.instance``,
    ``scene_assets``, ``client.openrouter``, ``client.pi_bridge``) is pulled in
    by this conftest's own imports, and test modules are imported at collection.
    Never import one for the first time inside a test body.

    ``tests/test_global_state_isolation.py`` checks that those modules really
    are imported before the tests run. It deliberately lives there rather than
    as an assertion here: anything raised before the ``yield`` aborts setup, so
    a single leaky test would error every later test in the worker instead of
    failing once with a usable message.
    """
    snapshot = {
        name: list(signal.receivers) for name, signal in async_signals.handlers.items()
    }
    yield
    for name, signal in async_signals.handlers.items():
        # Signals registered during the test start out with no receivers, so
        # clearing is the correct restore for them too.
        signal.receivers[:] = snapshot.get(name, [])


@pytest.fixture(autouse=True)
def restore_global_registries():
    """Undo writes to the process-wide agent and voice registries.

    ``bootstrap_engine()`` fills ``instance.AGENTS`` with throwaway agents and
    swaps ``voice_library.VOICE_LIBRARY`` for an empty one, and several tests
    rebind ``VOICE_LIBRARY`` directly. None of it is restored by the callers, so
    without this the last test to bootstrap decides what every later test in the
    worker sees.

    ``AGENTS`` is restored in place: ``talemate/server/agent_config.py`` and
    friends do ``from talemate.instance import AGENTS``, so rebinding it hands
    them a stale dict — the exact defect this suite already tripped over.
    """
    agents_snapshot = dict(instance.AGENTS)
    voice_library_snapshot = voice_library.VOICE_LIBRARY
    yield
    instance.AGENTS.clear()
    instance.AGENTS.update(agents_snapshot)
    voice_library.VOICE_LIBRARY = voice_library_snapshot


@pytest.fixture
def template_dir(tmp_path) -> str:
    """A world-state template directory of this test's own.

    Group/Collection operations write real YAML, so tests sharing one directory
    cannot run concurrently — and a shared directory that each test wipes on
    entry cannot survive being distributed across workers.
    """
    path = tmp_path / "templates"
    path.mkdir()
    return str(path)


@pytest.fixture
def isolate_signals():
    """Factory that clears a signal's receivers for the duration of the test
    (so handlers don't leak between tests) and restores them on teardown.
    Returns the isolated AsyncSignal objects for connecting test handlers."""
    restores = []

    def _isolate(*names):
        signals = []
        for name in names:
            sig = async_signals.get(name)
            restores.append((sig, list(sig.receivers)))
            sig.receivers.clear()
            signals.append(sig)
        return signals[0] if len(signals) == 1 else signals

    yield _isolate

    for sig, receivers in restores:
        sig.receivers.clear()
        sig.receivers.extend(receivers)


def connect_recorder(signal) -> list:
    """Connect a recording handler to a signal and return the list that
    received payloads are appended to."""
    received = []

    async def handler(payload):
        received.append(payload)

    signal.connect(handler)
    return received


# ---------------------------------------------------------------------------
# Mock classes
# ---------------------------------------------------------------------------


class MockClient(ClientBase):
    """LLM client stub that pops pre-defined responses from a queue."""

    def __init__(self, name: str):
        self.name = name
        self.remote_model_name = "test-model"
        self.current_status = "idle"
        self.prompt_history = []

    @property
    def enabled(self):
        return True

    async def send_prompt(
        self, prompt, kind="conversation", finalize=lambda x: x, retries=2, **kwargs
    ):
        response_stack = client_responses.get()
        self.prompt_history.append({"prompt": prompt, "kind": kind})
        if not response_stack:
            return ""
        return response_stack.popleft()


class MockMemoryAgent(talemate.agents.memory.MemoryAgent):
    """MemoryAgent with no-op persistence methods."""

    async def add_many(self, items: list[dict]):
        pass

    async def delete(self, filters: dict):
        pass


class MockScene(Scene):
    """Real Scene subclass with auto_progress forced on."""

    @property
    def auto_progress(self):
        return True


# ---------------------------------------------------------------------------
# Bootstrap helpers
# ---------------------------------------------------------------------------


def bootstrap_engine():
    """Instantiate all real agents (using MockMemoryAgent for memory)."""
    voice_library.VOICE_LIBRARY = voice_library.VoiceLibrary(voices={})
    for agent_type in agents.AGENT_CLASSES:
        if agent_type == "memory":
            agent = MockMemoryAgent()
        else:
            agent = agents.AGENT_CLASSES[agent_type]()
        instance.AGENTS[agent_type] = agent


def pytest_addoption(parser):
    """Add custom command-line options."""
    parser.addoption(
        "--update-baselines",
        action="store_true",
        default=False,
        help="Update baseline snapshot files instead of comparing against them.",
    )


@pytest.fixture
def update_baselines(request):
    """Whether to update baseline files instead of comparing."""
    return request.config.getoption("--update-baselines")


def bootstrap_scene(mock_scene):
    """Wire a MockClient and the mock_scene into every agent."""
    bootstrap_engine()
    client = MockClient("test_client")
    for agent in instance.AGENTS.values():
        agent.client = client
        agent.scene = mock_scene

    director = instance.get_agent("director")
    conversation = instance.get_agent("conversation")
    summarizer = instance.get_agent("summarizer")
    editor = instance.get_agent("editor")
    world_state = instance.get_agent("world_state")

    mock_scene.mock_client = client

    return {
        "director": director,
        "conversation": conversation,
        "summarizer": summarizer,
        "editor": editor,
        "world_state": world_state,
    }
