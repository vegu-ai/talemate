"""
Deterministic auto-layout for Talemate node graph JSON dicts.

The goal is a *readable* placement of freshly added nodes — not aesthetic
perfection. The algorithm is a stage-stratified vertical-band sweep: each
weakly-connected component of the target set is classified by the node
registries it contains, sorted vertically (Input chains on top, Stage
chains in numeric order, passthrough middle chains, Output chains at the
bottom), and then laid out horizontally using a topological depth sweep
with greedy row assignment to avoid overlaps.

Node heights are NOT read from the writer — the writer intentionally
leaves them unset and layout estimates them from socket / property counts
via ``_estimate_height``. This keeps collision avoidance honest for nodes
that actually render tall.

Usage::

    from talemate.game.engine.nodes.tools import layout_graph

    layout_graph(graph, new_node_ids=[id_a, id_b], anchor="right")

``anchor`` values:

* ``"right"`` — place the target set to the right of the existing bounding
  box, sharing the existing ``min_y``.
* ``"below"`` — place the target set below the existing bounding box,
  sharing the existing ``min_x``.
* ``"full"`` — relayout every node in the graph, starting at ``(0, 0)``.

Notes:

* Nodes outside the target set are never moved and never resized.
* Heights of nodes inside the target set are always overwritten with an
  estimate — the contract is "if you ask layout to position a node, it
  also sizes it."
* Groups, comments, and any non-node canvas elements are not touched.
* ``extends`` is not resolved — only the raw JSON of this graph is
  considered.
"""

from __future__ import annotations

import enum
from collections import defaultdict, deque
from itertools import groupby
from typing import Iterable

import pydantic
import structlog

from . import writer as writer_mod
from .writer import DEFAULT_NODE_HEIGHT, DEFAULT_NODE_WIDTH

log = structlog.get_logger("talemate.game.engine.nodes.tools.layout")

__all__ = [
    "layout_graph",
    "LayoutError",
    "LayoutOptions",
    "WCCKind",
]

# Default canvas metrics — chosen to match the rough shapes of shipped
# graphs. ``col_width = 360`` gives wires ~150 px of horizontal breathing
# room between a node's right edge (default node width 210) and the
# next column's left edge.
#
# ``DEFAULT_NODE_WIDTH`` / ``DEFAULT_NODE_HEIGHT`` are imported from
# ``writer`` so both modules agree on a single source of truth. The
# height fallback is used only when a node outside the target set is
# missing a ``height`` for bounding-box math; nodes inside the target
# set are always sized by ``_estimate_height``.
DEFAULT_COL_WIDTH = 360
DEFAULT_RIGHT_GAP = 300
DEFAULT_BELOW_GAP = 200


class LayoutError(ValueError):
    """Raised for malformed layout requests."""


class LayoutOptions(pydantic.BaseModel):
    """Tweakable metrics for the layout pass (defaults are fine)."""

    col_width: int = DEFAULT_COL_WIDTH
    right_gap: int = DEFAULT_RIGHT_GAP
    below_gap: int = DEFAULT_BELOW_GAP
    # Vertical gap between stage bands after the super-band merge.
    band_gap: int = 120
    # Height-aware packing: minimum vertical gap between two nodes
    # stacked in the same column.
    min_vertical_gap: int = 50
    # Height estimation formula inputs.
    title_bar_height: int = 20
    socket_row_height: int = 22
    padding: int = 0
    min_height: int = 60
    # Extra vertical space for the +/- buttons that DynamicSocketNodeBase
    # subclasses render at the bottom of the node.
    dynamic_socket_bonus: int = 30


# ---------------------------------------------------------------------------
# WCC classification
# ---------------------------------------------------------------------------


class WCCKind(enum.Enum):
    """The vertical band a weakly-connected component belongs to."""

    TOP = "top"  # has core/Input, no core/Stage
    STAGE = "stage"  # has core/Stage
    MIDDLE = "middle"  # no Input, no Output, no Stage
    BOTTOM = "bottom"  # has core/Output, no core/Input, no core/Stage


class WCCInfo(pydantic.BaseModel):
    """One weakly-connected component and its classification."""

    nodes: list[str]
    kind: WCCKind
    stage_value: int | None = None  # populated when kind == STAGE


# ---------------------------------------------------------------------------
# Graph accessors (private)
# ---------------------------------------------------------------------------


def _nodes(graph: dict) -> dict[str, dict]:
    return graph.get("nodes") or {}


def _edges(graph: dict) -> dict[str, list[str]]:
    return graph.get("edges") or {}


def _split_edge_node(endpoint: str) -> str | None:
    if "." not in endpoint:
        return None
    return endpoint.split(".", 1)[0]


def _node_rect(node: dict) -> tuple[int, int, int, int]:
    x = int(node.get("x", 0) or 0)
    y = int(node.get("y", 0) or 0)
    w = int(node.get("width", 0) or 0) or DEFAULT_NODE_WIDTH
    h = int(node.get("height", 0) or 0) or DEFAULT_NODE_HEIGHT
    return x, y, w, h


def _existing_bounds(graph: dict, target_set: set[str]) -> tuple[int, int, int, int]:
    """Return (min_x, min_y, max_x, max_y) for nodes NOT in the target set.

    If the "outside" set is empty (e.g. full relayout, or every node is
    targeted) the bounds collapse to ``(0, 0, 0, 0)``.
    """

    xs: list[int] = []
    ys: list[int] = []
    maxes_x: list[int] = []
    maxes_y: list[int] = []
    for nid, node in _nodes(graph).items():
        if nid in target_set:
            continue
        x, y, w, h = _node_rect(node)
        xs.append(x)
        ys.append(y)
        maxes_x.append(x + w)
        maxes_y.append(y + h)
    if not xs:
        return (0, 0, 0, 0)
    return (min(xs), min(ys), max(maxes_x), max(maxes_y))


# ---------------------------------------------------------------------------
# Height estimation
# ---------------------------------------------------------------------------


def _estimate_height(graph_node: dict, options: LayoutOptions) -> int:
    """Compute an estimated render height for a node from its class metadata.

    Formula::

        title_bar_height
          + (max(num_inputs, num_outputs) + num_properties) * socket_row_height
          + padding
          + dynamic_socket_bonus (if the class is a DynamicSocketNodeBase)

    Properties render as full widget rows **below** the socket area in
    LiteGraph, stacking vertically with the socket rows rather than
    being a small per-property bonus. Dynamic-socket nodes render
    ``+``/``-`` buttons at the bottom for adding/removing inputs; those
    take ~30 px and apply whether or not the instance currently has any
    dynamic inputs (the buttons are a class capability).

    Floored at ``options.min_height``. If the node's registry is not in
    the live ``NODES`` dict, falls back to ``options.min_height``.

    ``num_inputs`` includes any graph-level ``dynamic_inputs`` on the
    node, because dynamic inputs also render a socket row.
    """

    registry = graph_node.get("registry")
    if not registry:
        return options.min_height
    try:
        meta = writer_mod.get_node_metadata(registry)
    except writer_mod.UnknownRegistryError:
        return options.min_height

    num_static_inputs = len(meta.inputs)
    num_outputs = len(meta.outputs)
    num_properties = len(meta.properties)

    dyn = graph_node.get("dynamic_inputs") or []
    num_dynamic_inputs = len(dyn)
    num_inputs = num_static_inputs + num_dynamic_inputs

    rows = max(num_inputs, num_outputs) + num_properties
    estimated = (
        options.title_bar_height + rows * options.socket_row_height + options.padding
    )
    if meta.is_dynamic:
        estimated += options.dynamic_socket_bonus
    return max(estimated, options.min_height)


def _apply_estimated_heights(
    graph: dict, target_ids: set[str], options: LayoutOptions
) -> None:
    """Set ``height`` on each target node to an estimated value.

    Always overwrites the height for nodes in the target set — the
    contract is "if you ask layout to position a node, it also sizes it."
    Nodes outside the target set are not touched.
    """

    nodes = _nodes(graph)
    for nid in target_ids:
        node = nodes.get(nid)
        if node is None:
            continue
        node["height"] = _estimate_height(node, options)


# ---------------------------------------------------------------------------
# Weakly-connected components over a subset
# ---------------------------------------------------------------------------


def _wcc_over_subset(graph: dict, subset: set[str]) -> list[list[str]]:
    """Compute weakly-connected components restricted to ``subset``.

    Only edges with both endpoints in ``subset`` contribute to adjacency;
    edges leaving the subset (bridges to the outside world) don't merge
    components for our purposes. A node in ``subset`` with no internal
    edges becomes a singleton component.

    Returns a list of components, each a sorted ``list[str]`` of node ids.
    The outer list is sorted by the lexicographically-smallest node id of
    each component for deterministic iteration order.
    """

    parent: dict[str, str] = {nid: nid for nid in subset}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for src_key, targets in _edges(graph).items():
        s_node = _split_edge_node(src_key)
        if s_node is None or s_node not in subset:
            continue
        for tgt in targets:
            t_node = _split_edge_node(tgt)
            if t_node is None or t_node not in subset:
                continue
            union(s_node, t_node)

    buckets: dict[str, list[str]] = defaultdict(list)
    for nid in subset:
        buckets[find(nid)].append(nid)

    components = [sorted(comp) for comp in buckets.values()]
    components.sort(key=lambda comp: comp[0] if comp else "")
    return components


# ---------------------------------------------------------------------------
# Component classification
# ---------------------------------------------------------------------------


def _classify_wcc(graph: dict, node_ids: list[str]) -> WCCInfo:
    """Inspect the registries of the nodes in a component and pick a kind.

    Precedence when multiple flags apply::

        STAGE > TOP > BOTTOM > MIDDLE

    Rationale: a chain containing both an ``Input`` and a ``Stage`` is
    part of that Stage's band, not the top band. A chain with both
    ``Output`` and ``Input`` is a TOP (passthrough — the Input anchors
    it). A chain with ``Output`` only and no ``Stage`` is BOTTOM.
    """

    nodes = _nodes(graph)
    has_input = False
    has_output = False
    stage_values: list[int] = []

    for nid in node_ids:
        node = nodes.get(nid) or {}
        registry = node.get("registry") or ""
        if registry == "core/Input":
            has_input = True
        elif registry == "core/Output":
            has_output = True
        elif registry == "core/Stage":
            stage_prop = (node.get("properties") or {}).get("stage", 0)
            try:
                stage_values.append(int(stage_prop))
            except (TypeError, ValueError):
                stage_values.append(0)

    if stage_values:
        return WCCInfo(
            nodes=node_ids,
            kind=WCCKind.STAGE,
            stage_value=min(stage_values),
        )
    if has_input:
        return WCCInfo(nodes=node_ids, kind=WCCKind.TOP)
    if has_output:
        return WCCInfo(nodes=node_ids, kind=WCCKind.BOTTOM)
    return WCCInfo(nodes=node_ids, kind=WCCKind.MIDDLE)


def _band_group_key(info: WCCInfo) -> tuple:
    """Grouping key for the band-merging step in ``layout_graph``.

    Two WCCs share a key (and therefore get merged into one super-band)
    when they belong to the same vertical category — e.g. all BOTTOM
    components form one bottom band, all STAGE components with the same
    stage number form one stage band. This eliminates the fragmentation
    that arises when a graph has multiple WCCs of the same kind, which
    is common when each ``GetState\u2192Output`` emission pair is its own
    tiny 2-node WCC.

    The key shape mirrors the first two elements of ``_wcc_sort_key`` so
    that consecutive same-keyed entries are guaranteed to be adjacent in
    the sorted list (a precondition for ``itertools.groupby``).
    """

    if info.kind is WCCKind.TOP:
        return (0, 0)
    if info.kind is WCCKind.STAGE:
        return (1, info.stage_value)  # _classify_wcc guarantees non-None here
    if info.kind is WCCKind.MIDDLE:
        return (2, 0)
    return (3, 0)  # BOTTOM


def _wcc_sort_key(info: WCCInfo) -> tuple:
    """Vertical ordering key: TOP, STAGE(0), STAGE(1), ..., MIDDLE, BOTTOM.

    Within the same band, ties break on the lexicographically-smallest
    node id so the order is stable.
    """

    smallest = info.nodes[0] if info.nodes else ""
    if info.kind is WCCKind.TOP:
        return (0, 0, smallest)
    if info.kind is WCCKind.STAGE:
        return (1, info.stage_value, smallest)  # STAGE kind guarantees non-None
    if info.kind is WCCKind.MIDDLE:
        return (2, 0, smallest)
    return (3, 0, smallest)  # BOTTOM


# ---------------------------------------------------------------------------
# Topological column sweep for a single band
# ---------------------------------------------------------------------------


def _topological_depths(
    target_ids: set[str], internal_edges: list[tuple[str, str]]
) -> dict[str, int]:
    """Kahn's algorithm; isolated nodes get depth 0.

    A cycle (if any — the writer's ``connect()`` rejects these, but raw
    JSON could still have them) short-circuits: remaining nodes fall
    back to depth 0 to keep the layout robust.
    """

    adj: dict[str, set[str]] = defaultdict(set)
    indeg: dict[str, int] = {nid: 0 for nid in target_ids}
    for s, t in internal_edges:
        if t not in adj[s]:
            adj[s].add(t)
            indeg[t] = indeg.get(t, 0) + 1

    depths: dict[str, int] = {nid: 0 for nid in target_ids}
    queue: deque[str] = deque(nid for nid, d in indeg.items() if d == 0)
    while queue:
        nid = queue.popleft()
        for child in adj.get(nid, ()):
            candidate = depths[nid] + 1
            if candidate > depths[child]:
                depths[child] = candidate
            indeg[child] -= 1
            if indeg[child] == 0:
                queue.append(child)

    # Any nodes left with indeg > 0 are part of a cycle; leave them at 0
    # rather than dropping them.
    return depths


def _rects_overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)


class _BandPlacement(pydantic.BaseModel):
    """Internal result of placing a single band."""

    rects: list[tuple[int, int, int, int]] = pydantic.Field(default_factory=list)
    max_y: int = 0  # highest y + h across all placed nodes; 0 for empty


def _place_band(
    graph: dict,
    band_nodes: list[str],
    *,
    origin_x: int,
    origin_y: int,
    options: LayoutOptions,
) -> _BandPlacement:
    """Place one weakly-connected component as a topological column sweep.

    All nodes in ``band_nodes`` are positioned starting at
    ``(origin_x, origin_y)``.

    Packing is height-aware (per-column ``y_cursor``) and
    predecessor-aware (Sugiyama-layer barycenter heuristic): for each
    column past the first, unplaced nodes are sorted by the average y
    of their already-placed predecessors in earlier columns, so a child
    tends to land near the row of its parent(s). This eliminates the
    diamond wire crossings that a naive stable-id ordering would cause.
    """

    nodes = _nodes(graph)
    band_set = set(band_nodes)

    # Internal edges for topological sort (both endpoints in the band).
    internal_edges: list[tuple[str, str]] = []
    for src_key, targets in _edges(graph).items():
        s_node = _split_edge_node(src_key)
        if s_node is None or s_node not in band_set:
            continue
        for tgt in targets:
            t_node = _split_edge_node(tgt)
            if t_node is None or t_node not in band_set:
                continue
            if s_node == t_node:
                continue
            internal_edges.append((s_node, t_node))

    depths = _topological_depths(band_set, internal_edges)

    # Predecessor adjacency (parent set per node, restricted to the band).
    predecessors: dict[str, set[str]] = {nid: set() for nid in band_set}
    for s, t in internal_edges:
        predecessors[t].add(s)

    # Group by column (depth), nodes sorted by id for stable initial order.
    by_depth: dict[int, list[str]] = defaultdict(list)
    for nid in sorted(band_set):
        by_depth[depths.get(nid, 0)].append(nid)

    placement = _BandPlacement()

    # Per-column y cursor: next free y position for that column.
    column_cursors: dict[int, int] = {}
    # Track placed y positions so predecessor-aware sorting can average
    # over already-assigned rows.
    placed_y: dict[str, int] = {}

    # Build outgoing-edge index for the entry-point sort key (column 0),
    # restricted to edges whose BOTH endpoints live in this band. Any
    # edge that leaves the band is irrelevant to the BFS-to-deepest walk
    # and filtering it here keeps the inner loop tight.
    outgoing: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for src_key, targets in _edges(graph).items():
        s_node = _split_edge_node(src_key)
        if s_node is None or s_node not in band_set:
            continue
        for tgt in targets:
            t_node, _, t_socket = tgt.partition(".")
            if t_node and t_socket and t_node in band_set:
                outgoing[s_node].append((t_node, t_socket))

    def _input_socket_index(target_node_id: str, target_socket: str) -> int:
        """Return the index of ``target_socket`` in the target node's input
        list (static inputs from the class metadata followed by per-instance
        ``dynamic_inputs``). Falls back to a large sentinel when the socket
        can't be resolved, so it sorts to the end without crashing.
        """
        node = nodes.get(target_node_id) or {}
        registry = node.get("registry") or ""
        if not registry:
            return 999
        try:
            meta = writer_mod.get_node_metadata(registry)
        except writer_mod.UnknownRegistryError:
            return 999
        names = list(meta.inputs)
        for d in node.get("dynamic_inputs") or []:
            name = d.get("name") if isinstance(d, dict) else None
            if name:
                names.append(name)
        try:
            return names.index(target_socket)
        except ValueError:
            return 999

    def _entry_point_sort_key(nid: str) -> tuple:
        """Sort key for column-0 (no-predecessor) nodes.

        Priority order (highest-priority case wins):

        1. **``core/Input`` entry point** — sorted by its own ``num``
           property, so module inputs appear in interface-declaration
           order (``IN x`` with ``num=1`` sits above ``IN y`` with
           ``num=2``). Predecessor-aware placement then aligns each
           input's ``SET local.x`` counterpart next to it, producing
           horizontal IN-to-SET wires.
        2. **Deepest-descendant is ``core/Output``** — sorted by the
           descendant's ``num`` property. Makes the bottom emission band's
           ``GET\u2192Output`` pairs land in interface-declaration order.
        3. **General deepest-descendant case** — sorted by
           ``(descendant_id, socket_index)``. When entry-point chains
           converge on a sink (e.g. four ``IN``\u2192``SET`` chains feeding a
           ``Stage 0`` marker), siblings share their first sort component
           and differ only on socket order, so predecessor-aware placement
           downstream eliminates cross-column wire crossings into the
           convergence node.
        4. **No outgoing edges** — fall back to stable id order at the
           end of the sort.

        Cases 1 and 2 use string-prefixed tuple components (``"__input__"``
        / ``"__output__"``) to keep them in distinct sort spaces so
        cross-kind ordering stays predictable.
        """

        # Case 1: the entry point is itself a core/Input — use its num.
        node = nodes.get(nid) or {}
        if node.get("registry") == "core/Input":
            num_val = (node.get("properties") or {}).get("num", 0)
            try:
                num_int = int(num_val)
            except (TypeError, ValueError):
                num_int = 0
            return (0, ("__input__", num_int), nid)

        # BFS forward from nid, tracking depth. ``outgoing`` is already
        # pre-filtered to in-band edges, so no per-hop band check.
        visited: set[str] = {nid}
        bfs: deque[tuple[str, int]] = deque([(nid, 0)])
        candidates: list[tuple[int, str, int]] = []  # (depth, target_id, socket_idx)

        while bfs:
            current, depth = bfs.popleft()
            for t_node, t_socket in outgoing.get(current, ()):
                candidates.append(
                    (depth + 1, t_node, _input_socket_index(t_node, t_socket))
                )
                if t_node not in visited:
                    visited.add(t_node)
                    bfs.append((t_node, depth + 1))

        if not candidates:
            return (1, ("", 0), nid)

        # Pick the deepest reachable (descendant, socket). Tie-break on
        # lex-smallest (descendant_id, socket_index) so siblings that
        # converge on the same descendant share their first sort component
        # and differ only on socket order.
        candidates.sort(key=lambda c: (-c[0], c[1], c[2]))
        _, desc_id, socket_idx = candidates[0]

        # Case 2: deepest descendant is a core/Output — use its num
        # property (interface-declaration order).
        desc_node = nodes.get(desc_id) or {}
        if desc_node.get("registry") == "core/Output":
            num_val = (desc_node.get("properties") or {}).get("num", 0)
            try:
                num_int = int(num_val)
            except (TypeError, ValueError):
                num_int = 0
            return (0, ("__output__", num_int), nid)

        # Case 3: general deepest-descendant case.
        return (0, (desc_id, socket_idx), nid)

    for depth in sorted(by_depth):
        column_x = origin_x + depth * options.col_width
        candidates = by_depth[depth]

        if depth == 0:
            # First column: no predecessors, so we can't barycenter on
            # parents. Sort entry points by where their wires attach on
            # their successors instead — see ``_entry_point_sort_key``.
            ordered = sorted(candidates, key=_entry_point_sort_key)
        else:
            # Sort by preferred y = average y of placed predecessors in
            # earlier columns. Nodes with no placed predecessor go to
            # the end. Secondary key is the stable id so ties are
            # deterministic.
            def _preferred(nid: str) -> tuple[int, int, str]:
                placed_parents = [
                    placed_y[p] for p in predecessors.get(nid, ()) if p in placed_y
                ]
                if placed_parents:
                    avg = sum(placed_parents) // len(placed_parents)
                    return (0, avg, nid)
                return (1, 0, nid)

            ordered = sorted(candidates, key=_preferred)

        for nid in ordered:
            node = nodes[nid]
            _, _, w, h = _node_rect(node)

            # Preferred y from predecessors (ignored in column 0).
            preferred_y: int | None = None
            if depth > 0:
                placed_parents = [
                    placed_y[p] for p in predecessors.get(nid, ()) if p in placed_y
                ]
                if placed_parents:
                    preferred_y = sum(placed_parents) // len(placed_parents)

            cursor = column_cursors.get(depth, origin_y)
            if preferred_y is None:
                target_y = cursor
            else:
                # Never go above the cursor (that would shuffle the
                # order of already-placed nodes in this column).
                target_y = max(preferred_y, cursor)

            candidate = (column_x, target_y, w, h)
            # Height-aware collision check against anything already
            # placed in the band (protects against cross-column overlap
            # from the wider col_width or adjustment quirks).
            while any(_rects_overlap(candidate, r) for r in placement.rects):
                target_y += options.min_vertical_gap
                candidate = (column_x, target_y, w, h)

            cx, cy, cw, ch = candidate
            node["x"] = cx
            node["y"] = cy
            placement.rects.append(candidate)
            placed_y[nid] = cy
            column_cursors[depth] = cy + ch + options.min_vertical_gap
            if cy + ch > placement.max_y:
                placement.max_y = cy + ch

    return placement


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def layout_graph(
    graph: dict,
    *,
    new_node_ids: Iterable[str] | None = None,
    anchor: str = "right",
    options: LayoutOptions | None = None,
) -> None:
    """Mutate ``graph`` so the target node set is placed without overlap.

    Parameters
    ----------
    graph:
        Raw graph dict (as loaded from ``loader.load_graph``). Mutated
        in place — nothing is returned.
    new_node_ids:
        Exact set of nodes to reposition. If ``None``, every node
        currently sitting at ``(0, 0)`` is treated as needing placement.
    anchor:
        ``"right"``, ``"below"`` or ``"full"``. See module docstring.
    options:
        Optional :class:`LayoutOptions` overriding canvas metrics.
    """

    opts = options or LayoutOptions()
    if anchor not in ("right", "below", "full"):
        raise LayoutError(
            f"Unknown anchor '{anchor}'; expected 'right', 'below', or 'full'."
        )

    nodes = _nodes(graph)
    if not nodes:
        return

    # Resolve the target set.
    if anchor == "full":
        target_ids = set(nodes.keys())
    elif new_node_ids is not None:
        target_ids = set(new_node_ids)
        missing = target_ids - nodes.keys()
        if missing:
            raise LayoutError(
                f"Target set references unknown node ids: {sorted(missing)}"
            )
    else:
        target_ids = {
            nid
            for nid, n in nodes.items()
            if int(n.get("x", 0) or 0) == 0 and int(n.get("y", 0) or 0) == 0
        }

    if not target_ids:
        return

    # Step 1: estimate heights for every target node BEFORE we read any
    # rectangle for collision math.
    _apply_estimated_heights(graph, target_ids, opts)

    # Step 2: pick the anchor origin based on where everything else is.
    min_x, min_y, max_x, max_y = _existing_bounds(graph, target_ids)
    if anchor == "right":
        anchor_x = max_x + opts.right_gap if max_x else 0
        anchor_y = min_y
    elif anchor == "below":
        anchor_x = min_x
        anchor_y = max_y + opts.below_gap if max_y else 0
    else:  # full
        anchor_x = 0
        anchor_y = 0

    # Step 3: compute weakly-connected components of the target set and
    # classify each one so we can stack them vertically.
    components = _wcc_over_subset(graph, target_ids)
    wcc_infos = [_classify_wcc(graph, comp) for comp in components]
    wcc_infos.sort(key=_wcc_sort_key)

    # Step 4: place each band, stacking downward. WCCs of the same kind
    # (e.g. multiple BOTTOM components, or both halves of a single STAGE)
    # are merged into one super-band so they read as one cohesive group
    # rather than as multiple fragmented bands separated by ``band_gap``.
    # The y-cursor starts at anchor_y and advances by (band_height +
    # band_gap) after each merged band.
    y_cursor = anchor_y
    for _key, group_iter in groupby(wcc_infos, key=_band_group_key):
        group = list(group_iter)
        # Flatten all nodes from all WCCs in this group into a single
        # band. ``_place_band`` builds its own internal topology, so
        # passing nodes from multiple disconnected sub-WCCs just means
        # each sub-WCC contributes its own column structure to the band.
        band_nodes: list[str] = [nid for info in group for nid in info.nodes]
        placement = _place_band(
            graph,
            band_nodes,
            origin_x=anchor_x,
            origin_y=y_cursor,
            options=opts,
        )
        if not placement.rects:
            continue
        band_height = placement.max_y - y_cursor
        y_cursor = y_cursor + band_height + opts.band_gap
