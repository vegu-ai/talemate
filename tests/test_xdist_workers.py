"""Tests for the pytest-xdist worker-count hook in conftest.

The suite runs distributed by default (`addopts = -n auto`), and the worker
count comes from `pytest_xdist_auto_num_workers`. Getting it wrong is
expensive in both directions: too many workers on a CPU-limited container
makes every run slower, too few leaves cores idle.
"""

import sys
import types

import pytest

import conftest


@pytest.fixture
def cgroup_files(tmp_path, monkeypatch):
    """Point the cgroup lookups at a temporary directory.

    Returns the (v2, v1_quota, v1_period) paths; a test writes only the ones
    whose cgroup version it is standing in for, leaving the rest absent.
    """
    v2 = tmp_path / "cpu.max"
    v1_quota = tmp_path / "cpu.cfs_quota_us"
    v1_period = tmp_path / "cpu.cfs_period_us"
    monkeypatch.setattr(conftest, "_CGROUP_V2_CPU_MAX", v2)
    monkeypatch.setattr(conftest, "_CGROUP_V1_CPU_QUOTA", v1_quota)
    monkeypatch.setattr(conftest, "_CGROUP_V1_CPU_PERIOD", v1_period)
    return v2, v1_quota, v1_period


class TestCgroupCpuQuota:
    def test_reads_cgroup_v2_quota(self, cgroup_files):
        v2, _, _ = cgroup_files
        v2.write_text("400000 100000")

        assert conftest._cgroup_cpu_quota() == 4.0

    def test_cgroup_v2_max_means_unrestricted(self, cgroup_files):
        v2, _, _ = cgroup_files
        v2.write_text("max 100000")

        assert conftest._cgroup_cpu_quota() is None

    def test_reads_cgroup_v1_quota_when_v2_is_absent(self, cgroup_files):
        _, v1_quota, v1_period = cgroup_files
        v1_quota.write_text("200000")
        v1_period.write_text("100000")

        assert conftest._cgroup_cpu_quota() == 2.0

    def test_cgroup_v1_negative_quota_means_unrestricted(self, cgroup_files):
        _, v1_quota, v1_period = cgroup_files
        v1_quota.write_text("-1")
        v1_period.write_text("100000")

        assert conftest._cgroup_cpu_quota() is None

    def test_returns_none_when_no_cgroup_files_exist(self, cgroup_files):
        assert conftest._cgroup_cpu_quota() is None


@pytest.fixture
def cpu_topology(monkeypatch):
    """Control every signal the worker-count hook consults.

    Arguments to the returned setter:

    - ``affinity``: usable cores, or None for a platform without
      ``os.sched_getaffinity`` (Windows, macOS), where the hook falls back to
      ``os.cpu_count()``.
    - ``cpu_count``: what ``os.cpu_count()`` reports; defaults to ``affinity``.
    - ``quota``: cgroup CPU quota, or None for unrestricted.
    - ``physical``: psutil's physical-core count, or None to have psutil report
      nothing. Pass ``psutil=False`` for psutil not being installed at all.
    """

    def _set(affinity=8, quota=None, physical=None, psutil=True, cpu_count=...):
        # The hook consults this before anything else, and a contributor who
        # exports it would otherwise get None back from every test here.
        monkeypatch.delenv("PYTEST_XDIST_AUTO_NUM_WORKERS", raising=False)

        if affinity is None:
            # raising=False: the attribute is absent on non-Linux to begin with.
            monkeypatch.delattr(conftest.os, "sched_getaffinity", raising=False)
        else:
            monkeypatch.setattr(
                conftest.os,
                "sched_getaffinity",
                lambda pid: set(range(affinity)),
                raising=False,
            )

        if cpu_count is ...:
            cpu_count = affinity
        monkeypatch.setattr(conftest.os, "cpu_count", lambda: cpu_count)
        monkeypatch.setattr(conftest, "_cgroup_cpu_quota", lambda: quota)

        if psutil:
            fake = types.SimpleNamespace(cpu_count=lambda logical=True: physical)
            monkeypatch.setitem(sys.modules, "psutil", fake)
        else:
            # A None entry in sys.modules makes `import psutil` raise ImportError.
            monkeypatch.setitem(sys.modules, "psutil", None)

    return _set


class _Options:
    def __init__(self, numprocesses="auto"):
        self.numprocesses = numprocesses


class _Config:
    def __init__(self, numprocesses="auto"):
        self.option = _Options(numprocesses)


class TestAutoNumWorkers:
    def test_zero_workers_on_a_single_cpu(self, cpu_topology):
        """0 tells xdist to stay in-process — distributing on one CPU is a
        pure loss (a second interpreter plus IPC for every test)."""
        cpu_topology(affinity=32, quota=1.0)

        assert conftest.pytest_xdist_auto_num_workers(_Config()) == 0

    def test_quota_wins_over_visible_cpu_count(self, cpu_topology):
        """A container can see every host core while being allowed a few."""
        cpu_topology(affinity=32, quota=4.0)

        assert conftest.pytest_xdist_auto_num_workers(_Config()) == 4

    def test_affinity_is_honoured_without_any_quota(self, cpu_topology):
        """`--cpuset-cpus`, taskset and Slurm pin cores without setting a
        quota, so affinity has to be consulted on its own."""
        cpu_topology(affinity=2, quota=None)

        assert conftest.pytest_xdist_auto_num_workers(_Config()) == 2

    def test_caps_at_max_test_workers(self, cpu_topology):
        cpu_topology(affinity=64, quota=None)

        assert (
            conftest.pytest_xdist_auto_num_workers(_Config())
            == conftest.MAX_TEST_WORKERS
        )

    def test_fractional_quota_rounds_down_to_serial(self, cpu_topology):
        """0.5 of a CPU is less than one, so there is nothing to distribute."""
        cpu_topology(affinity=8, quota=0.5)

        assert conftest.pytest_xdist_auto_num_workers(_Config()) == 0

    def test_env_override_defers_to_xdist(self, cpu_topology, monkeypatch):
        """Returning None lets xdist's own implementation run, which is the
        only one that reads its documented override."""
        cpu_topology(affinity=8, quota=None)
        monkeypatch.setenv("PYTEST_XDIST_AUTO_NUM_WORKERS", "3")

        assert conftest.pytest_xdist_auto_num_workers(_Config()) is None

    def test_topology_fixture_clears_the_xdist_override(
        self, cpu_topology, monkeypatch
    ):
        """Pins `cpu_topology`'s `delenv`. Without it every test in this class
        returns None for anyone who has the override exported — and CI, where
        it is unset, could never notice the guard had been removed."""
        monkeypatch.setenv("PYTEST_XDIST_AUTO_NUM_WORKERS", "3")
        cpu_topology(affinity=4, quota=None)

        assert conftest.pytest_xdist_auto_num_workers(_Config()) == 4

    def test_auto_prefers_physical_cores(self, cpu_topology):
        """`-n auto` means physical cores; affinity counts hyperthreads, so
        oversubscribing them on a CPU-bound suite just adds contention."""
        cpu_topology(affinity=8, quota=None, physical=4)

        assert conftest.pytest_xdist_auto_num_workers(_Config("auto")) == 4

    def test_logical_uses_the_hyperthread_count(self, cpu_topology):
        cpu_topology(affinity=8, quota=None, physical=4)

        assert conftest.pytest_xdist_auto_num_workers(_Config("logical")) == 8

    def test_quota_still_wins_over_physical_core_count(self, cpu_topology):
        cpu_topology(affinity=16, quota=2.0, physical=8)

        assert conftest.pytest_xdist_auto_num_workers(_Config()) == 2

    def test_falls_back_to_cpu_count_without_sched_getaffinity(self, cpu_topology):
        """Windows and macOS have no ``os.sched_getaffinity`` — the branch every
        non-Linux contributor actually runs."""
        cpu_topology(affinity=None, cpu_count=4, quota=None)

        assert conftest.pytest_xdist_auto_num_workers(_Config()) == 4

    def test_unknown_cpu_count_falls_back_to_serial(self, cpu_topology):
        """``os.cpu_count()`` returns None when it cannot tell."""
        cpu_topology(affinity=None, cpu_count=None, quota=None)

        assert conftest.pytest_xdist_auto_num_workers(_Config()) == 0

    def test_single_physical_core_behind_hyperthreads_is_serial(self, cpu_topology):
        """One worker is the worst of both worlds — the full IPC and startup
        cost for no parallelism — so the `< 2` check has to be applied to the
        clamped count, not the count before it."""
        cpu_topology(affinity=4, quota=None, physical=1)

        assert conftest.pytest_xdist_auto_num_workers(_Config("auto")) == 0

    def test_logical_still_uses_hyperthreads_on_one_physical_core(self, cpu_topology):
        cpu_topology(affinity=4, quota=None, physical=1)

        assert conftest.pytest_xdist_auto_num_workers(_Config("logical")) == 4

    def test_missing_psutil_falls_back_to_the_affinity_count(self, cpu_topology):
        """Without psutil there is no way to tell physical cores from
        hyperthreads, so the usable-CPU count stands in for both."""
        cpu_topology(affinity=6, quota=None, psutil=False)

        assert conftest.pytest_xdist_auto_num_workers(_Config()) == 6
