import json
import shutil
import subprocess
from pathlib import Path

import pytest


BOOTSTRAP = Path(__file__).resolve().parents[1] / "install-utils" / "pnpm.cjs"


@pytest.fixture
def pnpm_installation(tmp_path):
    root = tmp_path / "Talemate with spaces"
    frontend = root / "talemate_frontend"
    frontend.mkdir(parents=True)
    (frontend / "package.json").write_text(
        json.dumps({"packageManager": "pnpm@12.4.1+sha512.abcdef"})
    )
    npm = tmp_path / "npm.cjs"
    npm.write_text(
        r"""
const fs = require('node:fs');
const path = require('node:path');
const args = process.argv.slice(2);
const settings = JSON.parse(fs.readFileSync(path.join(__dirname, 'settings.json')));
fs.appendFileSync(path.join(__dirname, 'npm-calls.jsonl'), JSON.stringify(args) + '\n');
if (settings.npmExit) process.exit(settings.npmExit);
const prefix = args[args.indexOf('--prefix') + 1];
const pkg = path.join(prefix, 'node_modules', 'pnpm');
fs.mkdirSync(pkg, {recursive: true});
fs.writeFileSync(path.join(pkg, 'package.json'), JSON.stringify({
    version: settings.version,
    bin: {pnpm: 'custom-entry.cjs'},
}));
fs.writeFileSync(path.join(pkg, 'custom-entry.cjs'), settings.source);
"""
    )
    settings = {
        "version": "12.4.1",
        "source": r"""
const fs = require('node:fs');
if (process.argv[2] === '--version') {
    process.stdout.write('12.4.1\n');
} else {
    fs.writeFileSync('invocation.json', JSON.stringify({
        args: process.argv.slice(2), cwd: process.cwd(),
        path: process.env.PATH, node: process.execPath,
    }));
    process.exit(process.argv.includes('--fail') ? 23 : 0);
}
""",
    }
    (tmp_path / "settings.json").write_text(json.dumps(settings))
    return root, npm, settings


def invoke(root, npm, *args):
    node = shutil.which("node")
    assert node, "Node.js is required to test portable pnpm provisioning"
    return subprocess.run(
        [
            node,
            "-e",
            "const {runPnpm} = require(process.argv[1]);"
            "try { process.exitCode = runPnpm(process.argv[2],"
            "JSON.parse(process.argv[4]), process.argv[3]); }"
            "catch (error) { console.error(error.message); process.exitCode = 1; }",
            str(BOOTSTRAP),
            str(root),
            str(npm),
            json.dumps(args),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_installs_exact_pin_locally_and_forwards_arguments(pnpm_installation):
    root, npm, _ = pnpm_installation
    result = invoke(root, npm, "install", "--frozen-lockfile", "argument with spaces")
    assert result.returncode == 0, result.stderr
    calls = [
        json.loads(line)
        for line in (npm.parent / "npm-calls.jsonl").read_text().splitlines()
    ]
    assert len(calls) == 1
    assert calls[0][-1] == "pnpm@12.4.1"
    assert calls[0][calls[0].index("--prefix") + 1] == str(
        root / "embedded_node" / "pnpm"
    )
    assert {
        "--global=false",
        "--ignore-scripts=false",
        "--include=optional",
        "--package-lock=false",
    } <= set(calls[0])
    invocation = json.loads(
        (root / "talemate_frontend" / "invocation.json").read_text()
    )
    assert invocation["args"] == [
        "install",
        "--frozen-lockfile",
        "argument with spaces",
    ]
    assert invocation["cwd"] == str(root / "talemate_frontend")
    assert invocation["path"].startswith(str(Path(invocation["node"]).parent))


def test_reuses_working_pin_without_npm(pnpm_installation):
    root, npm, _ = pnpm_installation
    assert invoke(root, npm, "--version").returncode == 0
    npm.unlink()
    result = invoke(root, npm, "build")
    assert result.returncode == 0, result.stderr
    assert len((npm.parent / "npm-calls.jsonl").read_text().splitlines()) == 1


@pytest.mark.parametrize(
    "damage", ["wrong_version", "missing_bin", "broken_bin", "bad_manifest"]
)
def test_repairs_invalid_local_installation(pnpm_installation, damage):
    root, npm, _ = pnpm_installation
    assert invoke(root, npm, "--version").returncode == 0
    pkg = root / "embedded_node" / "pnpm" / "node_modules" / "pnpm"
    if damage == "wrong_version":
        (pkg / "package.json").write_text(
            json.dumps({"version": "1.0.0", "bin": {"pnpm": "custom-entry.cjs"}})
        )
    elif damage == "missing_bin":
        (pkg / "custom-entry.cjs").unlink()
    elif damage == "broken_bin":
        (pkg / "custom-entry.cjs").write_text("process.exit(1)")
    else:
        (pkg / "package.json").write_text("invalid json")
    result = invoke(root, npm, "build")
    assert result.returncode == 0, result.stderr
    assert len((npm.parent / "npm-calls.jsonl").read_text().splitlines()) == 2


@pytest.mark.parametrize("pin", ["pnpm@latest", "npm@12.4.1", "pnpm@^12.4.1", None])
def test_rejects_unpinned_package_manager_before_install(pnpm_installation, pin):
    root, npm, _ = pnpm_installation
    (root / "talemate_frontend" / "package.json").write_text(
        json.dumps({"packageManager": pin})
    )
    result = invoke(root, npm, "build")
    assert result.returncode == 1
    assert "must pin an exact pnpm version" in result.stderr
    assert not (npm.parent / "npm-calls.jsonl").exists()


@pytest.mark.parametrize("failure", ["npm", "verification", "missing_npm"])
def test_provisioning_failure_stops_before_frontend(pnpm_installation, failure):
    root, npm, settings = pnpm_installation
    if failure == "npm":
        settings["npmExit"] = 17
    elif failure == "verification":
        settings["version"] = "1.0.0"
    else:
        npm.unlink()
    (npm.parent / "settings.json").write_text(json.dumps(settings))
    result = invoke(root, npm, "build")
    assert result.returncode == 1
    assert {
        "npm": "npm exited 17",
        "verification": "could not be verified",
        "missing_npm": "Bundled npm not found",
    }[failure] in result.stderr
    assert not (root / "talemate_frontend" / "invocation.json").exists()


def test_propagates_frontend_failure(pnpm_installation):
    root, npm, _ = pnpm_installation
    result = invoke(root, npm, "build", "--fail")
    assert result.returncode == 23


@pytest.mark.parametrize(
    ("node_path", "platform", "expected"),
    [
        (
            r"C:\Talemate with spaces\embedded_node\node.exe",
            "win32",
            r"C:\Talemate with spaces\embedded_node\node_modules\npm\bin\npm-cli.js",
        ),
        (
            "/Talemate with spaces/embedded_node/bin/node",
            "linux",
            "/Talemate with spaces/embedded_node/lib/node_modules/npm/bin/npm-cli.js",
        ),
        (
            "/opt/node/bin/node",
            "darwin",
            "/opt/node/lib/node_modules/npm/bin/npm-cli.js",
        ),
    ],
)
def test_selects_npm_beside_the_running_node(node_path, platform, expected):
    result = subprocess.run(
        [
            "node",
            "-e",
            "process.stdout.write(require(process.argv[1]).bundledNpm(process.argv[2], process.argv[3]))",
            str(BOOTSTRAP),
            node_path,
            platform,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == expected
