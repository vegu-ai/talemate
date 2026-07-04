"""
Documentation access tools for the help agent.

Exposes the bundled markdown documentation (docs/ in the talemate root) to the
LLM through three focal callbacks: search, read a full document, and read a
single section of a document. A generated index (docs-index.yaml, shipped next
to this module) provides path/title/summary for every documentation page so
the LLM can decide what to open.
"""

import re
from pathlib import Path

import structlog
import yaml

from talemate.path import TALEMATE_ROOT

__all__ = [
    "DOCS_DIR",
    "DOCS_SITE_URL",
    "doc_url",
    "docs_available",
    "load_docs_index",
    "search_docs",
    "read_doc",
    "read_doc_section",
]

log = structlog.get_logger("talemate.agents.help.docs")

DOCS_DIR = TALEMATE_ROOT / "docs"
DOCS_INDEX_FILE = Path(__file__).parent / "docs-index.yaml"

# published manual (mkdocs site_url) - doc references shown to the user link here
DOCS_SITE_URL = "https://vegu-ai.github.io/talemate/"

MAX_SEARCH_RESULTS = 40
MAX_RESULTS_PER_FILE = 5
MAX_DOC_CHARS = 15000

_index_cache: list[dict] | None = None


def docs_available() -> bool:
    return DOCS_DIR.is_dir()


def load_docs_index() -> list[dict]:
    """Load the generated documentation index (path, title, summary per page)."""
    global _index_cache
    if _index_cache is not None:
        return _index_cache
    try:
        _index_cache = yaml.safe_load(DOCS_INDEX_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.error("help.docs.index.load.error", file=str(DOCS_INDEX_FILE), error=e)
        _index_cache = []
    return _index_cache


def doc_url(path: str) -> str:
    """
    Map a documentation path to its URL on the published manual
    (mkdocs directory URLs: `a/b.md` -> `a/b/`, `a/index.md` -> `a/`).
    """
    path = path.removesuffix(".md")
    if path.endswith("index"):
        path = path[: -len("index")]
    path = path.strip("/")
    return f"{DOCS_SITE_URL}{path}/" if path else DOCS_SITE_URL


def _resolve_doc_path(path: str) -> Path | None:
    """Resolve a relative documentation path, refusing anything outside DOCS_DIR."""
    try:
        resolved = (DOCS_DIR / path).resolve()
        resolved.relative_to(DOCS_DIR.resolve())
    except (ValueError, OSError):
        return None
    if resolved.suffix.lower() != ".md" or not resolved.is_file():
        return None
    return resolved


def _strip_markdown_noise(content: str) -> str:
    """Remove image references - they carry no information for the LLM."""
    return re.sub(r"!\[[^\]]*\]\([^)]*\)", "", content)


def _truncate(content: str, limit: int = MAX_DOC_CHARS) -> str:
    if len(content) <= limit:
        return content
    return (
        content[:limit]
        + f"\n\n[... truncated at {limit} characters - read a specific section for more]"
    )


def search_docs(query: str) -> list[dict] | str:
    """
    Case-insensitive search across all documentation pages.

    The query is treated as a regular expression, falling back to a literal
    match when it does not compile. Returns matches as
    {path, line, text} dicts.
    """
    if not docs_available():
        return "Documentation directory is not available in this installation."

    try:
        pattern = re.compile(query, re.IGNORECASE)
    except re.error:
        pattern = re.compile(re.escape(query), re.IGNORECASE)

    results: list[dict] = []

    for md_file in sorted(DOCS_DIR.rglob("*.md")):
        try:
            lines = md_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        per_file = 0
        for line_number, line in enumerate(lines, start=1):
            if not pattern.search(line):
                continue
            results.append(
                {
                    "path": str(md_file.relative_to(DOCS_DIR)),
                    "line": line_number,
                    "text": line.strip()[:300],
                }
            )
            per_file += 1
            if per_file >= MAX_RESULTS_PER_FILE:
                break
        if len(results) >= MAX_SEARCH_RESULTS:
            results = results[:MAX_SEARCH_RESULTS]
            break

    if not results:
        return f"No matches for '{query}'. Try a broader or different term."
    return results


def read_doc(path: str) -> dict | str:
    """Read a full documentation page. Path is relative to the docs root."""
    if not docs_available():
        return "Documentation directory is not available in this installation."

    resolved = _resolve_doc_path(path)
    if not resolved:
        return f"Document '{path}' does not exist. Use paths from the documentation index or search results."

    content = _strip_markdown_noise(resolved.read_text(encoding="utf-8"))
    return {
        "path": path,
        "url": doc_url(path),
        "content": _truncate(content),
    }


def read_doc_section(path: str, section: str) -> dict | str:
    """
    Read a single section of a documentation page.

    The section is matched against markdown headings (case-insensitive,
    substring). Returns the heading's content including any subsections.
    """
    if not docs_available():
        return "Documentation directory is not available in this installation."

    resolved = _resolve_doc_path(path)
    if not resolved:
        return f"Document '{path}' does not exist. Use paths from the documentation index or search results."

    lines = resolved.read_text(encoding="utf-8").splitlines()
    heading_re = re.compile(r"^(#{1,6})\s+(.*)$")

    needle = section.strip().lower().lstrip("#").strip()
    start: int | None = None
    level = 0
    headings: list[str] = []

    for i, line in enumerate(lines):
        match = heading_re.match(line)
        if not match:
            continue
        headings.append(match.group(2).strip())
        if start is None and needle in match.group(2).strip().lower():
            start = i
            level = len(match.group(1))

    if start is None:
        return {
            "path": path,
            "error": f"No heading matching '{section}' found.",
            "available_sections": headings,
        }

    end = len(lines)
    for i in range(start + 1, len(lines)):
        match = heading_re.match(lines[i])
        if match and len(match.group(1)) <= level:
            end = i
            break

    content = _strip_markdown_noise("\n".join(lines[start:end]).strip())
    return {
        "path": path,
        "url": doc_url(path),
        "section": lines[start].lstrip("#").strip(),
        "content": _truncate(content),
    }
