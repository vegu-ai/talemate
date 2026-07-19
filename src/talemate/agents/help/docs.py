"""
Documentation access tools for the help agent.

Exposes the bundled markdown documentation (docs/ in the talemate root) to the
LLM through four focal callbacks: look up pages by topic (find_docs, a
keyword-scored match over the generated index), full-text search, read a full
document, and read a single section of a document. The generated index
(docs-index.yaml, shipped next to this module) provides path/title/summary for
every page; only a compact section overview of it is injected into the prompt.
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
    "docs_section_overview",
    "find_docs",
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

# Short content descriptions for the section overview injected into the
# LLM prompt (the per-page index stays OUT of the prompt - pages are
# located at runtime via find_docs). Prefixes not listed fall back to the
# prefix itself.
SECTION_DESCRIPTIONS = {
    "getting-started": "Installation (Windows/Linux/Docker), first launch, connecting a client, loading the first scene",
    "user-guide": "Top-level guides: interacting with scenes, saving/restoring, world state, tracking states, character import, scene tools, debug tools, visual and voice library",
    "user-guide/agents": "Every agent's settings and behavior: conversation, creator, director, editor, help, memory, narrator, summarizer, visualizer, voice, world state",
    "user-guide/apis": "Third-party inference API key setup (OpenAI, Anthropic, Google, OpenRouter, ...)",
    "user-guide/app-settings": "Application settings dialog pages",
    "user-guide/clients": "LLM client types, setup and per-client options",
    "user-guide/howto": "Tutorials and walkthroughs, including the multi-part dynamic scenario crash course",
    "user-guide/integrations": "Third-party integrations",
    "user-guide/node-editor": "Node editor: core concepts (graphs, states, functions, events, modules, packaging) and the complete node reference documenting every node's registry path, sockets and properties",
    "user-guide/prompts": "Prompt template overrides",
    "user-guide/templates": "World-state templates (attributes, details, spices, writing styles, ...)",
    "user-guide/world-editor": "World editor: scene, characters, world entries, context DB, history, pins, suggestions",
    "dev": "Developer documentation: agent/client internals, templates, third-party reference",
}

# tokens too generic to contribute to find_docs scoring
_FIND_STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "to",
    "of",
    "in",
    "on",
    "for",
    "with",
    "how",
    "do",
    "does",
    "what",
    "where",
    "when",
    "is",
    "are",
    "my",
    "i",
    "use",
    "using",
    "it",
    "can",
    "you",
}

FIND_DOCS_LIMIT = 5

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


def docs_section_overview() -> list[dict]:
    """
    The documentation grouped into sections, for the LLM prompt: one entry
    per section with its path prefix, page count and a content description.
    """
    counts: dict[str, int] = {}
    for entry in load_docs_index():
        parts = entry["path"].split("/")
        if len(parts) < 2:
            continue
        if parts[0] == "user-guide" and len(parts) > 2:
            prefix = "/".join(parts[:2])
        else:
            prefix = parts[0]
        counts[prefix] = counts.get(prefix, 0) + 1
    return [
        {
            "prefix": prefix,
            "count": count,
            "description": SECTION_DESCRIPTIONS.get(prefix, prefix),
        }
        for prefix, count in sorted(counts.items())
    ]


def _stem(token: str) -> str:
    """
    Naive morphological fold: plurals ("node" matches "nodes", but not
    e.g. "class") and -ing forms ("track" matches "tracking"). Applied to
    query and index tokens alike, so folded forms stay consistent.
    """
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        token = token[:-1]
    if len(token) > 5 and token.endswith("ing"):
        token = token[:-3]
    return token


def _token_seq(text: str) -> list[str]:
    """
    Normalize text into an ordered word-token sequence: camelCase split
    (so registry paths like scene/GetCharacter match the spaced page
    titles), lowercased, split on non-alphanumerics, plural-folded.
    """
    decamel = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    return [_stem(t) for t in re.split(r"[^a-z0-9]+", decamel.lower()) if t]


def _token_set(text: str) -> set[str]:
    """
    Word tokens for matching: both the camelCase-split tokens and the raw
    ones, so "koboldcpp" matches "KoboldCpp" as well as "Kobold Cpp".
    """
    raw = {_stem(t) for t in re.split(r"[^a-z0-9]+", text.lower()) if t}
    return raw | set(_token_seq(text))


def find_docs(query: str, limit: int = FIND_DOCS_LIMIT) -> list[dict] | str:
    """
    Look up documentation pages by topic.

    Keyword-scored match over the full index (path, title, summary) -
    deterministic, no LLM involved. Tokens match on word boundaries (a
    query token "set" does not match "settings"). Returns the best
    matches with their path, title, summary and manual URL.
    """
    query_seq = _token_seq(query or "")
    if not query_seq:
        return "Empty query."
    stopwords = _FIND_STOPWORDS | {_stem(w) for w in _FIND_STOPWORDS}
    tokens = {t for t in _token_set(query or "") if len(t) > 1 and t not in stopwords}
    # word-boundary phrase, only meaningful for multi-word queries
    phrase = f" {' '.join(query_seq)} " if len(query_seq) > 1 else None

    scored: list[tuple[float, dict]] = []
    for entry in load_docs_index():
        title_set = _token_set(entry["title"])
        path_set = _token_set(entry["path"])
        summary_set = _token_set(entry["summary"])
        score = 0.0
        for token in tokens:
            if token in title_set:
                score += 3
            if token in path_set:
                score += 2
            if token in summary_set:
                score += 1
        if phrase:
            if phrase in f" {' '.join(_token_seq(entry['title']))} ":
                score += 5
            elif (
                phrase in f" {' '.join(_token_seq(entry['path']))} "
                or phrase in f" {' '.join(_token_seq(entry['summary']))} "
            ):
                score += 3
        if score > 0:
            scored.append((score, entry))
    scored.sort(key=lambda item: (-item[0], item[1]["path"]))
    if not scored:
        return (
            f"No documentation pages match '{query}'. Try different terms, "
            f"or search_docs for a full-text search."
        )
    return [
        {
            "path": entry["path"],
            "title": entry["title"],
            "summary": entry["summary"],
            "url": doc_url(entry["path"]),
        }
        for _, entry in scored[:limit]
    ]


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
