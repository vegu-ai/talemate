"""
Guards user-visible schema copy against drift from the settings UI.

Client and agent configuration moved out of standalone modals into the
settings pages (PR #202), which left a trail of stale instructions in
``description=`` / ``note=`` copy ("this tab", "close and open this window",
"Settings -> Application -> ..."). This module re-checks that copy on every
run:

* prong (i)  - retired-UI vocabulary must not reappear
* prong (ii) - a ``Settings -> X`` navigation path must name a settings group
  that still exists in the frontend registry

Only string literals passed as ``description=`` / ``note=`` keyword arguments
are scanned (``AgentAction``, ``AgentActionConfig``, ``Field``, ``ExtraField``,
...). Scanning whole files instead produces roughly nine false positives per
real hit - "context window", "multi-modal", "dialogue", browser tabs.
"""

import ast
import re
import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src" / "talemate"
SETTINGS_REGISTRY_JS = (
    REPO_ROOT / "talemate_frontend" / "src" / "utils" / "appSettingsRegistry.js"
)

COPY_KWARGS = {"description", "note"}

# (label, pattern). `modal` is word-bounded and excludes multi-modal/multimodal,
# which is legitimate model vocabulary.
BANNED_PHRASES = [
    ("modal", re.compile(r"(?<!multi[\s-])(?<!multi)\bmodals?\b", re.IGNORECASE)),
    ("popup", re.compile(r"\bpop[\s-]?ups?\b", re.IGNORECASE)),
    ("its own tab", re.compile(r"its own tab", re.IGNORECASE)),
    ("this tab", re.compile(r"this tab", re.IGNORECASE)),
    ("this window", re.compile(r"this window", re.IGNORECASE)),
    ("close and open", re.compile(r"close and open", re.IGNORECASE)),
    ("close and reopen", re.compile(r"close and reopen", re.IGNORECASE)),
    ("dialog pages", re.compile(r"dialog pages", re.IGNORECASE)),
]

SETTINGS_PATH_RE = re.compile(r"Settings\s*(?:->|→|>)\s*([A-Za-z][A-Za-z0-9 ]*)")

# (path relative to src/talemate, phrase or navigation segment) pairs that are
# legitimate despite matching above. Every entry needs a reason.
#
# Currently empty: restricting the scan to `description=` / `note=` kwargs
# already excludes the known-good uses (the generation error dialog docstrings
# in client/base.py and server/api.py, the scene status popup docstring in
# game/engine/api/signals.py) because those live in docstrings and comments,
# not in schema copy.
ALLOWLIST: set[tuple[str, str]] = set()


class SettingsRegistryParseError(RuntimeError):
    """Raised when appSettingsRegistry.js can no longer be parsed."""


def _strip_js_noise(text: str) -> str:
    """Blank out string literals and line comments so brace counting is safe."""
    out = []
    i = 0
    length = len(text)
    quote = None
    while i < length:
        char = text[i]
        if quote:
            if char == "\\":
                out.append("  ")
                i += 2
                continue
            out.append("\n" if char == "\n" else " ")
            if char == quote:
                quote = None
            i += 1
            continue
        if char in "'\"`":
            quote = char
            out.append(" ")
            i += 1
            continue
        if char == "/" and i + 1 < length and text[i + 1] == "/":
            while i < length and text[i] != "\n":
                out.append(" ")
                i += 1
            continue
        out.append(char)
        i += 1
    return "".join(out)


def load_settings_group_titles(
    registry_path: Path = SETTINGS_REGISTRY_JS,
) -> list[str]:
    """
    Parse the live settings group titles out of appSettingsRegistry.js.

    Fails loudly rather than degrading: a missing file, an unparseable
    SETTINGS_GROUPS block or zero groups all raise, because a silent empty
    result would turn the navigation-path check into a no-op.
    """
    hint = (
        f"Update {Path(__file__).name} (load_settings_group_titles) to match the "
        f"new structure of {registry_path.name}."
    )

    if not registry_path.is_file():
        raise SettingsRegistryParseError(
            f"Settings registry not found at {registry_path}. {hint}"
        )

    source = registry_path.read_text()
    marker = re.search(r"export\s+const\s+SETTINGS_GROUPS\s*=\s*\[", source)
    if not marker:
        raise SettingsRegistryParseError(
            f"No `export const SETTINGS_GROUPS = [` in {registry_path}. {hint}"
        )

    masked = _strip_js_noise(source)
    depth = 0
    end = None
    for index in range(marker.end() - 1, len(masked)):
        char = masked[index]
        if char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
            if depth == 0:
                end = index
                break
    if end is None:
        raise SettingsRegistryParseError(
            f"Unbalanced SETTINGS_GROUPS array in {registry_path}. {hint}"
        )

    # depth 1 == inside the array, depth 2 == inside a group object, so a
    # `title:` seen at depth 2 is a group title (page titles sit at depth 4).
    titles = []
    depth = 0
    group_start = None
    for index in range(marker.end() - 1, end + 1):
        char = masked[index]
        if char in "[{":
            depth += 1
            if depth == 2:
                group_start = index
        elif char in "]}":
            if depth == 2 and group_start is not None:
                block = source[group_start : index + 1]
                title = re.search(r"\btitle\s*:\s*['\"]([^'\"]+)['\"]", block)
                if not title:
                    raise SettingsRegistryParseError(
                        f"SETTINGS_GROUPS entry without a `title` in {registry_path}. "
                        f"{hint}"
                    )
                if not re.search(r"\bpages\s*:\s*\[", block):
                    raise SettingsRegistryParseError(
                        f"SETTINGS_GROUPS entry '{title.group(1)}' has no `pages` "
                        f"array in {registry_path}. {hint}"
                    )
                titles.append(title.group(1))
                group_start = None
            depth -= 1

    if not titles:
        raise SettingsRegistryParseError(
            f"Parsed zero settings groups from {registry_path}. {hint}"
        )

    return titles


def _module_string_constants(tree: ast.Module) -> dict[str, str]:
    constants = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Constant) or not isinstance(
            node.value.value, str
        ):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                constants[target.id] = node.value.value
    return constants


def _literal_value(node: ast.AST, constants: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    if isinstance(node, ast.JoinedStr):
        parts = [
            part.value
            for part in node.values
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        ]
        return " ".join(parts) if parts else None
    return None


def collect_schema_copy(filepath: Path) -> list[tuple[int, str, str]]:
    """Return (lineno, kwarg, text) for every description=/note= string literal."""
    tree = ast.parse(filepath.read_text(), str(filepath))
    constants = _module_string_constants(tree)

    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg not in COPY_KWARGS:
                continue
            text = _literal_value(keyword.value, constants)
            if text:
                found.append((keyword.value.lineno, keyword.arg, text))
    return found


def collect_source_files() -> list[Path]:
    return sorted(SRC_DIR.rglob("*.py"))


def test_no_retired_ui_phrases_in_schema_copy():
    """Schema copy must not describe UI that PR #202 retired."""
    source_files = collect_source_files()
    assert source_files, f"No python files found in {SRC_DIR}"

    failures = []
    for filepath in source_files:
        rel_path = filepath.relative_to(SRC_DIR)
        for lineno, kwarg, text in collect_schema_copy(filepath):
            for label, pattern in BANNED_PHRASES:
                if not pattern.search(text):
                    continue
                if (str(rel_path), label) in ALLOWLIST:
                    continue
                failures.append(
                    f"  {rel_path}:{lineno} ({kwarg}=) - retired UI term "
                    f"'{label}' in: {text[:120]!r}"
                )

    if failures:
        msg = (
            f"Found {len(failures)} reference(s) to retired UI in schema copy.\n"
            f"Client and agent configuration live on settings pages now - reword "
            f"the copy, or add an entry to ALLOWLIST if the hit is legitimate.\n"
            + "\n".join(failures)
        )
        pytest.fail(msg)


def test_settings_navigation_paths_point_at_live_groups():
    """`Settings -> X` copy must name a group the settings sidebar still has."""
    group_titles = load_settings_group_titles()
    known = {title.lower() for title in group_titles}

    source_files = collect_source_files()
    assert source_files, f"No python files found in {SRC_DIR}"

    failures = []
    for filepath in source_files:
        rel_path = filepath.relative_to(SRC_DIR)
        for lineno, kwarg, text in collect_schema_copy(filepath):
            for match in SETTINGS_PATH_RE.finditer(text):
                segment = match.group(1).strip()
                if segment.lower() in known:
                    continue
                if (str(rel_path), segment) in ALLOWLIST:
                    continue
                failures.append(
                    f"  {rel_path}:{lineno} ({kwarg}=) - 'Settings -> {segment}' "
                    f"is not a settings group in: {text[:120]!r}"
                )

    if failures:
        msg = (
            f"Found {len(failures)} stale settings navigation path(s).\n"
            f"Live groups: {', '.join(group_titles)}\n" + "\n".join(failures)
        )
        pytest.fail(msg)


def test_settings_registry_parse_fails_loudly(tmp_path):
    """A registry the test can no longer parse must error, never pass quietly."""
    with pytest.raises(SettingsRegistryParseError, match="not found"):
        load_settings_group_titles(tmp_path / "missing.js")

    no_marker = tmp_path / "no_marker.js"
    no_marker.write_text("export const API_PROVIDERS = [];\n")
    with pytest.raises(SettingsRegistryParseError, match="SETTINGS_GROUPS"):
        load_settings_group_titles(no_marker)

    empty = tmp_path / "empty.js"
    empty.write_text("export const SETTINGS_GROUPS = [];\n")
    with pytest.raises(SettingsRegistryParseError, match="zero settings groups"):
        load_settings_group_titles(empty)

    reshaped = tmp_path / "reshaped.js"
    reshaped.write_text(
        "export const SETTINGS_GROUPS = [\n"
        "    { title: 'Connections', icon: 'mdi-connection' },\n"
        "];\n"
    )
    with pytest.raises(SettingsRegistryParseError, match="no `pages` array"):
        load_settings_group_titles(reshaped)

    untitled = tmp_path / "untitled.js"
    untitled.write_text("export const SETTINGS_GROUPS = [\n    { pages: [] },\n];\n")
    with pytest.raises(SettingsRegistryParseError, match="without a `title`"):
        load_settings_group_titles(untitled)


def test_settings_registry_groups_are_parsed():
    """Sanity check that the real registry yields the expected group shape."""
    titles = load_settings_group_titles()
    assert "Connections" in titles, (
        f"Expected a 'Connections' settings group, parsed: {titles}"
    )
