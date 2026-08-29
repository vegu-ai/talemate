"""
Argparse-based CLI wrapping ``analysis.py``.

Subcommands map 1:1 to analysis functions. Every subcommand supports
``--json`` for machine-readable output. Default output is dense, grep-
friendly text using 8-char short UUID prefixes.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path
from typing import Any, Callable, TextIO

import pydantic

from . import analysis
from .loader import GraphLoadError, load_graph

__all__ = ["main", "build_parser"]


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------

EXIT_OK = 0
EXIT_STRUCT_ERROR = 1
EXIT_REGISTRY_PROBLEMS = 2


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


def _fmt_summary(s: analysis.GraphSummary) -> str:
    out = io.StringIO()
    out.write(f"title:        {s.title}\n")
    out.write(f"id:           {s.id}\n")
    out.write(f"registry:     {s.registry}\n")
    out.write(f"base_type:    {s.base_type}\n")
    out.write(f"extends:      {s.extends}\n")
    out.write(f"nodes:        {s.node_count}\n")
    out.write("  by category:\n")
    for cat, count in s.nodes_by_category.items():
        out.write(f"    {cat:<20} {count}\n")
    out.write(f"stage nodes:  {s.stage_node_count}\n")
    out.write(
        f"interface:    inputs={s.input_count} outputs={s.output_count} "
        f"module_properties={s.module_property_count}\n"
    )
    if s.group_titles:
        out.write("groups:\n")
        for t in s.group_titles:
            out.write(f"  - {t}\n")
    return out.getvalue().rstrip()


def _fmt_list_nodes(entries: list[analysis.NodeListEntry]) -> str:
    if not entries:
        return "(no nodes match)"
    lines = []
    reg_w = max((len(e.registry or "") for e in entries), default=0)
    reg_w = min(reg_w, 50)
    for e in entries:
        lines.append(f"{e.short_id}  {(e.registry or ''):<{reg_w}}  {e.title}")
    return "\n".join(lines)


def _fmt_node_details(d: analysis.NodeDetails) -> str:
    out = io.StringIO()
    out.write(f"{d.short_id}  {d.title}\n")
    out.write(f"  id:        {d.id}\n")
    out.write(f"  registry:  {d.registry}  (registered={d.registered})\n")
    out.write(f"  base_type: {d.base_type}\n")
    out.write(f"  pos:       x={d.x} y={d.y} w={d.width} h={d.height}\n")
    if d.properties:
        out.write("  properties:\n")
        for k, v in d.properties.items():
            v_str = repr(v)
            if len(v_str) > 100:
                v_str = v_str[:97] + "..."
            out.write(f"    {k} = {v_str}\n")
    out.write("  inputs:\n")
    if not d.inputs:
        out.write("    (none)\n")
    for inp in d.inputs:
        if inp.connected and inp.source is not None:
            out.write(
                f"    [x] {inp.name:<20} <- {inp.source.short_id}.{inp.source.socket}\n"
            )
        else:
            out.write(f"    [ ] {inp.name:<20} (unconnected)\n")
    out.write("  outputs:\n")
    if not d.outputs:
        out.write("    (none)\n")
    for op in d.outputs:
        if not op.consumers:
            out.write(f"    [ ] {op.name:<20} (no consumers)\n")
        else:
            out.write(f"    [x] {op.name:<20} ->\n")
            for c in op.consumers:
                out.write(f"          {c.short_id}.{c.socket}\n")
    return out.getvalue().rstrip()


def _fmt_edges(edges: list[analysis.EdgeInfo]) -> str:
    if not edges:
        return "(no edges)"
    lines = []
    for e in edges:
        lines.append(
            f"{e.source_short}.{e.source_socket}  ->  "
            f"{e.target_short}.{e.target_socket}"
        )
    return "\n".join(lines)


def _fmt_feeds(r: analysis.FeedsResult) -> str:
    out = io.StringIO()
    out.write(f"target: {r.target_short}.{r.target_socket}\n")
    if r.source is None:
        out.write("source: (unconnected)\n")
    else:
        out.write(f"source: {r.source.short_id}.{r.source.socket}\n")
        out.write(f"  title:    {r.source_node_title}\n")
        out.write(f"  registry: {r.source_node_registry}\n")
    return out.getvalue().rstrip()


def _fmt_consumers(r: analysis.ConsumersResult) -> str:
    out = io.StringIO()
    out.write(f"source: {r.source_short}.{r.source_socket}\n")
    if not r.consumers:
        out.write("consumers: (none)\n")
    else:
        out.write(f"consumers ({len(r.consumers)}):\n")
        for c in r.consumers:
            out.write(f"  -> {c.target_short}.{c.target_socket}\n")
    return out.getvalue().rstrip()


def _fmt_trace(t: analysis.TraceNode, *, indent: int = 0) -> str:
    out = io.StringIO()
    prefix = "  " * indent
    via = f" ({t.via_socket})" if t.via_socket else ""
    markers = []
    if t.cycle:
        markers.append("CYCLE")
    if t.truncated:
        markers.append("DEPTH")
    marker_str = f" [{', '.join(markers)}]" if markers else ""
    out.write(f"{prefix}{t.short_id}  {t.title}  <{t.registry}>{via}{marker_str}\n")
    for child in t.children:
        out.write(_fmt_trace(child, indent=indent + 1))
    return out.getvalue()


def _fmt_stage_map(r: analysis.StageMapResult) -> str:
    out = io.StringIO()
    out.write(f"chains: {len(r.chains)}\n")
    for chain in r.chains:
        out.write(
            f"  chain {chain.index}: nodes={len(chain.node_ids)} "
            f"stage_nodes={len(chain.stage_node_ids)} stages={chain.stages}\n"
        )
    out.write(f"stage nodes: {len(r.stage_nodes)}\n")
    for s in r.stage_nodes:
        out.write(
            f"  chain {s.chain_index}  stage {s.stage:<4} {s.short_id}  {s.title}\n"
        )
    if r.unstaged_node_ids:
        out.write(
            f"unstaged components: {len(r.unstaged_node_ids)} node(s) "
            f"in chains without a stage marker (default priority)\n"
        )
    return out.getvalue().rstrip()


def _fmt_check_registries(r: analysis.RegistryCheckResult) -> str:
    out = io.StringIO()
    out.write(
        f"checked: {r.checked_registry_count} registry strings, "
        f"{r.checked_base_type_count} base_type strings\n"
    )
    if not r.unknown_registries and not r.unknown_base_types:
        out.write("ok: no unknown registries or base types\n")
        return out.getvalue().rstrip()
    if r.unknown_registries:
        out.write(f"unknown registries ({len(r.unknown_registries)}):\n")
        for p in r.unknown_registries:
            out.write(f"  {p.short_id}  {p.registry}  ({p.title})\n")
    if r.unknown_base_types:
        out.write(f"unknown base types ({len(r.unknown_base_types)}):\n")
        for p in r.unknown_base_types:
            out.write(f"  {p.short_id}  {p.base_type}  ({p.title})\n")
    return out.getvalue().rstrip()


# ---------------------------------------------------------------------------
# Output dispatch
# ---------------------------------------------------------------------------


def _emit(
    result: pydantic.BaseModel | list[pydantic.BaseModel],
    *,
    json_out: bool,
    text_formatter: Callable[[Any], str],
    out_stream: TextIO,
) -> None:
    if json_out:
        if isinstance(result, list):
            data = [r.model_dump(mode="json") for r in result]
            out_stream.write(json.dumps(data, indent=2))
        else:
            out_stream.write(result.model_dump_json(indent=2))
        out_stream.write("\n")
        return
    out_stream.write(text_formatter(result))
    out_stream.write("\n")


# ---------------------------------------------------------------------------
# Argparse plumbing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m talemate.game.engine.nodes.tools",
        description=(
            "Read-only static analysis for Talemate node graph JSON files, "
            "plus the node glossary docs generator."
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add_graph_arg(p: argparse.ArgumentParser) -> None:
        p.add_argument("graph", help="Path to a node graph JSON file")
        p.add_argument(
            "--json", dest="json_out", action="store_true", help="Emit JSON output"
        )

    p_summary = sub.add_parser("summary", help="Top-level graph summary")
    add_graph_arg(p_summary)

    p_list = sub.add_parser("list-nodes", help="List nodes; filter by registry/title")
    add_graph_arg(p_list)
    p_list.add_argument("--registry", help="Substring filter on node registry")
    p_list.add_argument("--title", help="Substring filter on node title")

    p_node = sub.add_parser("node", help="Show details for a single node")
    add_graph_arg(p_node)
    p_node.add_argument("node_id", help="Node id (full or unique prefix)")

    p_edges = sub.add_parser("edges", help="List edges, optionally filtered")
    add_graph_arg(p_edges)
    p_edges.add_argument("--from", dest="from_node", help="Filter by source node")
    p_edges.add_argument("--to", dest="to_node", help="Filter by target node")

    p_feeds = sub.add_parser("feeds", help="What feeds a given input socket?")
    add_graph_arg(p_feeds)
    p_feeds.add_argument("target", help="<node_id_or_prefix>.<socket>")

    p_cons = sub.add_parser("consumers", help="What consumes a given output socket?")
    add_graph_arg(p_cons)
    p_cons.add_argument("source", help="<node_id_or_prefix>.<socket>")

    p_trace = sub.add_parser("trace", help="Forward trace from a node")
    add_graph_arg(p_trace)
    p_trace.add_argument("start", help="Node id (full or unique prefix)")
    p_trace.add_argument("--depth", type=int, default=3)

    p_rtrace = sub.add_parser("rtrace", help="Backward trace from a node")
    add_graph_arg(p_rtrace)
    p_rtrace.add_argument("end", help="Node id (full or unique prefix)")
    p_rtrace.add_argument("--depth", type=int, default=3)

    p_stages = sub.add_parser("stages", help="Show core/Stage chains")
    add_graph_arg(p_stages)

    p_check = sub.add_parser(
        "check-registries", help="Verify every registry string is known to the runtime"
    )
    add_graph_arg(p_check)

    p_glossary = sub.add_parser(
        "glossary",
        help="Generate the node glossary docs pages from the live registry",
    )
    glossary_mode = p_glossary.add_mutually_exclusive_group(required=True)
    glossary_mode.add_argument(
        "--write", action="store_true", help="Render and write all glossary pages"
    )
    glossary_mode.add_argument(
        "--check",
        action="store_true",
        help="Verify the committed pages match a fresh render (exit 1 on drift)",
    )
    p_glossary.add_argument(
        "--docs-root",
        help="Override the output directory (default: docs/user-guide/node-editor/reference/nodes)",
    )

    return parser


def _run(args: argparse.Namespace, out_stream: TextIO, err_stream: TextIO) -> int:
    # Ensure every Talemate node type is registered before any command
    # runs. Loading once up-front gives consistent behavior across
    # commands and surfaces loader errors before we start analyzing.
    analysis.ensure_registry_loaded()

    if args.cmd == "glossary":
        from . import glossary

        docs_root = Path(args.docs_root) if args.docs_root else None
        if args.check:
            return glossary.check_pages(docs_root)
        return glossary.write_pages(docs_root)

    try:
        graph = load_graph(args.graph)
    except GraphLoadError as exc:
        err_stream.write(f"error: {exc}\n")
        return EXIT_STRUCT_ERROR

    cmd = args.cmd
    json_out = args.json_out

    try:
        if cmd == "summary":
            result = analysis.summarize(graph)
            _emit(
                result,
                json_out=json_out,
                text_formatter=_fmt_summary,
                out_stream=out_stream,
            )

        elif cmd == "list-nodes":
            result = analysis.list_nodes(
                graph,
                registry_pattern=args.registry,
                title_pattern=args.title,
            )
            _emit(
                result,
                json_out=json_out,
                text_formatter=_fmt_list_nodes,
                out_stream=out_stream,
            )

        elif cmd == "node":
            result = analysis.get_node(graph, args.node_id)
            _emit(
                result,
                json_out=json_out,
                text_formatter=_fmt_node_details,
                out_stream=out_stream,
            )

        elif cmd == "edges":
            result = analysis.list_edges(
                graph, from_node=args.from_node, to_node=args.to_node
            )
            _emit(
                result,
                json_out=json_out,
                text_formatter=_fmt_edges,
                out_stream=out_stream,
            )

        elif cmd == "feeds":
            result = analysis.feeds(graph, args.target)
            _emit(
                result,
                json_out=json_out,
                text_formatter=_fmt_feeds,
                out_stream=out_stream,
            )

        elif cmd == "consumers":
            result = analysis.consumers(graph, args.source)
            _emit(
                result,
                json_out=json_out,
                text_formatter=_fmt_consumers,
                out_stream=out_stream,
            )

        elif cmd == "trace":
            result = analysis.trace_forward(graph, args.start, depth=args.depth)
            _emit(
                result,
                json_out=json_out,
                text_formatter=_fmt_trace,
                out_stream=out_stream,
            )

        elif cmd == "rtrace":
            result = analysis.trace_backward(graph, args.end, depth=args.depth)
            _emit(
                result,
                json_out=json_out,
                text_formatter=_fmt_trace,
                out_stream=out_stream,
            )

        elif cmd == "stages":
            result = analysis.stage_map(graph)
            _emit(
                result,
                json_out=json_out,
                text_formatter=_fmt_stage_map,
                out_stream=out_stream,
            )

        elif cmd == "check-registries":
            result = analysis.check_registries(graph)
            _emit(
                result,
                json_out=json_out,
                text_formatter=_fmt_check_registries,
                out_stream=out_stream,
            )
            if result.has_problems:
                return EXIT_REGISTRY_PROBLEMS

        else:  # pragma: no cover - argparse enforces this
            err_stream.write(f"error: unknown command {cmd}\n")
            return EXIT_STRUCT_ERROR

    except ValueError as exc:
        err_stream.write(f"error: {exc}\n")
        return EXIT_STRUCT_ERROR

    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return _run(args, sys.stdout, sys.stderr)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
