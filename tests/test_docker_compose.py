import json
import os
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
from packaging.markers import Marker, default_environment


ROOT = Path(__file__).parent.parent
COMPOSE_AVAILABLE = (
    shutil.which("docker") is not None
    and subprocess.run(
        ["docker", "compose", "version"],
        capture_output=True,
        check=False,
    ).returncode
    == 0
)
PORTS = {5050: 5050, 8082: 8082}
CPU_COMMAND = "docker compose -f docker-compose.cpu.yml up"
COMPOSE_DEFAULTS = {
    "PYTHONPATH": "",
    "TALEMATE_BACKEND_PORT": "5050",
    "TALEMATE_FRONTEND_PORT": "8082",
    "VITE_TALEMATE_BACKEND_WEBSOCKET_URL": "",
}
ENVIRONMENT_KEYS = {
    "PYTHONPATH",
    "PYTHONUNBUFFERED",
    "TALEMATE_BACKEND_PORT",
    "TALEMATE_FRONTEND_PORT",
    "VITE_TALEMATE_BACKEND_WEBSOCKET_URL",
}
VOLUME_TARGETS = {
    "/app/chroma",
    "/app/config.yaml",
    "/app/pi",
    "/app/scenes",
    "/app/secrets",
    "/app/templates",
    "/app/tts",
}


def render_compose(*files: str) -> dict:
    command = ["docker", "compose"]
    for compose_file in files:
        command.extend(["-f", compose_file])
    command.extend(["config", "--format", "json"])
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        check=True,
        env={**os.environ, **COMPOSE_DEFAULTS},
        text=True,
    )
    return json.loads(result.stdout)


def assert_runtime_contract(service: dict, *, gpu: bool, local_build: bool) -> None:
    ports = {int(port["target"]): int(port["published"]) for port in service["ports"]}
    assert ports == PORTS
    assert {volume["target"] for volume in service["volumes"]} == VOLUME_TARGETS
    assert set(service["environment"]) == ENVIRONMENT_KEYS

    devices = (
        service.get("deploy", {})
        .get("resources", {})
        .get("reservations", {})
        .get("devices", [])
    )
    if gpu:
        assert devices == [{"driver": "nvidia", "count": -1, "capabilities": ["gpu"]}]
    else:
        assert devices == []

    if local_build:
        assert service["image"] == "talemate:local"
        assert service["pull_policy"] == "build"
        assert service["build"]["dockerfile"] == "Dockerfile"
    else:
        assert service["image"] == "ghcr.io/vegu-ai/talemate:latest"
        assert "build" not in service


@pytest.mark.skipif(not COMPOSE_AVAILABLE, reason="Docker Compose CLI is unavailable")
@pytest.mark.parametrize(
    ("files", "gpu", "local_build"),
    [
        pytest.param((), True, False, id="default-cuda-image"),
        pytest.param(("docker-compose.cpu.yml",), False, False, id="cpu-image"),
        pytest.param(
            ("docker-compose.manual.yml",), False, True, id="standalone-cpu-build"
        ),
        pytest.param(
            ("docker-compose.yml", "docker-compose.manual.yml"),
            True,
            True,
            id="cuda-build",
        ),
        pytest.param(
            ("docker-compose.cpu.yml", "docker-compose.manual.yml"),
            False,
            True,
            id="cpu-build",
        ),
    ],
)
def test_documented_compose_invocations_render_complete_service(
    files: tuple[str, ...], gpu: bool, local_build: bool
):
    service = render_compose(*files)["services"]["talemate"]

    assert_runtime_contract(service, gpu=gpu, local_build=local_build)


@pytest.mark.skipif(not COMPOSE_AVAILABLE, reason="Docker Compose CLI is unavailable")
def test_render_compose_ignores_ambient_port_overrides(monkeypatch):
    monkeypatch.setenv("TALEMATE_FRONTEND_PORT", "9090")
    monkeypatch.setenv("TALEMATE_BACKEND_PORT", "6060")

    service = render_compose("docker-compose.cpu.yml")["services"]["talemate"]
    ports = {int(port["target"]): int(port["published"]) for port in service["ports"]}

    assert ports == PORTS


def applies_to_docker(package: dict) -> bool:
    markers = package.get("resolution-markers")
    if not markers:
        return True

    environment = default_environment()
    environment.update(
        platform_machine="x86_64",
        platform_system="Linux",
        python_full_version="3.11.0",
        python_version="3.11",
        sys_platform="linux",
    )
    return any(Marker(marker).evaluate(environment) for marker in markers)


def test_locked_torch_build_includes_cuda():
    with (ROOT / "uv.lock").open("rb") as lock_file:
        packages = tomllib.load(lock_file)["package"]

    docker_torch_packages = [
        package
        for package in packages
        if package["name"] == "torch" and applies_to_docker(package)
    ]

    assert len(docker_torch_packages) == 1
    torch = docker_torch_packages[0]
    assert "+cu" in torch["version"]
    assert torch["source"]["registry"].startswith("https://download.pytorch.org/whl/cu")


def test_cpu_opt_out_is_shown_on_install_and_startup_failure_paths():
    install = (ROOT / "docs/getting-started/installation/docker.md").read_text()
    advanced = (
        ROOT / "docs/getting-started/advanced/change-host-and-port.md"
    ).read_text()
    environment_variables = (
        ROOT / "docs/getting-started/advanced/environment-variables.md"
    ).read_text()
    troubleshooting = (
        ROOT / "docs/getting-started/installation/troubleshoot.md"
    ).read_text()

    assert CPU_COMMAND in install
    assert CPU_COMMAND in advanced
    assert CPU_COMMAND in troubleshooting
    assert "default and CPU-only Compose configurations" in environment_variables
    assert "working NVIDIA Container Toolkit" in troubleshooting
    assert 'could not select device driver "nvidia"' in troubleshooting
