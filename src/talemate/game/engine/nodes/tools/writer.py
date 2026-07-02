"""
Programmatic mutation API for Talemate node graph JSON dicts.

The functions here take an already-loaded ``graph: dict`` and mutate it in
place — the mirror image of ``analysis.py``, which is strictly read-only.
Pure primitive functions are the core surface; ``GraphWriter`` is an
ergonomic class that wraps them and adds file I/O.

Note on node sizes: the writer does NOT assign a default ``height`` to new
nodes. Height belongs to the layout pass (``tools.layout.layout_graph``),
which estimates it from the node's socket and property counts so collision
avoidance actually has a realistic rectangle to work with. Callers that
need a pinned height can still pass one explicitly. Width is still set to
a fixed default because every node in the repo uses the same canvas width.

Node metadata (static inputs, outputs, properties, ``base_type``) is read
from the live ``NODES`` class registry via a lightweight in-process cache
that instantiates each class once. We deliberately avoid
``registry.export_node_definitions()`` for this cache because that helper
calls ``PropertyField.model_dump()``, which in turn calls user-supplied
``generate_choices`` callables — several of those touch runtime-only state
(the websocket handler, the active scene, etc.) and crash outside a live
Talemate session. The instance-based probe here is the same pattern
``analysis.py`` uses in ``_static_socket_names`` and matches the
frontend-facing exporter's own instantiation step.

Known limitations:

* The writer does NOT keep the graph's top-level ``inputs`` / ``outputs``
  / ``module_properties`` mirror arrays in sync when interior Input /
  Output / ModuleProperty nodes are added or removed. Those arrays are
  computed at runtime from the interior nodes, but some shipped graphs
  (notably director actions) serialise them anyway. Callers that care
  about those arrays should regenerate them manually.
* The writer does NOT resolve ``extends``. It operates on raw JSON.
* The writer does NOT check socket *type* compatibility; many sockets in
  the codebase are typed ``any`` and strict type checks would fight real
  graphs. It only checks that sockets exist and that fan-in is at most 1.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Iterable

import pydantic
import structlog

from . import analysis
from .analysis import ensure_registry_loaded, resolve_node_id, split_socket_path
from .loader import load_graph

log = structlog.get_logger("talemate.game.engine.nodes.tools.writer")

__all__ = [
    # class
    "GraphWriter",
    # pure primitives
    "add_node",
    "remove_node",
    "connect",
    "disconnect",
    "add_dynamic_input",
    "remove_dynamic_input",
    "add_group",
    # metadata helpers
    "get_node_metadata",
    "clear_metadata_cache",
    "NodeMetadata",
    "GroupColor",
    # exceptions
    "WriterError",
    "UnknownRegistryError",
    "UnknownSocketError",
    "UnknownPropertyError",
    "AlreadyConnectedError",
    "NotConnectedError",
    "CycleError",
    "DynamicInputError",
    "NodeNotFoundError",
    "GroupError",
]


# ---------------------------------------------------------------------------
# Group color palette — matches the LiteGraph presets exposed in the
# frontend's "Create Group from Selection" submenu (see
# ``talemate_frontend/src/utils/recentNodes.js``). Each constant is the
# preset's ``groupcolor`` hex value, which is what gets stored on the
# group's ``color`` field in the graph JSON. Use these by name for
# readability — the agent picks which group gets which color based on
# the cluster's purpose.
# ---------------------------------------------------------------------------


class GroupColor:
    """Named group-color constants matching the LiteGraph preset palette.

    These are the same colors the frontend's right-click "Create Group
    from Selection" menu offers, so auto-generated groups visually match
    the convention used by hand-built graphs.
    """

    INPUT = "#88A"  # blue       — input collection / passthrough
    OUTPUT = "#8A8"  # green      — output emission
    PROCESS = "#3f789e"  # pale_blue  — main computation stages
    PREPARE = "#8AA"  # cyan       — setup / preconditions
    VALIDATION = "#b58b2a"  # yellow     — validation / guards
    FUNCTION = "#b06634"  # brown      — function definitions
    SPECIAL = "#a1309b"  # purple     — helpers / orphans / one-offs
    ERROR_HANDLING = "#A88"  # red        — error-handler chains
    UX = "#207e7e"  # teal       — user-facing UX nodes


# Default canvas dimensions used when a node in ``add_group``'s target
# set hasn't been sized by the layout pass yet (rare — call layout first).
DEFAULT_NODE_WIDTH = 210
DEFAULT_NODE_HEIGHT = 100


# Matches the frontend's group-creation padding constants (see
# ``talemate_frontend/src/utils/groupInteractions.js``). Auto-groups
# should look identical to user-created ones, so we mirror the same
# numbers rather than picking our own.
GROUP_PADDING = 25
GROUP_TOP_PADDING = 45  # padding + 20
GROUP_TITLE_HEIGHT = 20  # LiteGraph.NODE_TITLE_HEIGHT default
GROUP_MIN_WIDTH = 140
GROUP_MIN_HEIGHT = 80
GROUP_DEFAULT_FONT_SIZE = 24


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class WriterError(Exception):
    """Base class for all writer-layer errors."""


class UnknownRegistryError(WriterError):
    """A registry path is not present in the live ``NODES`` dict."""


class UnknownSocketError(WriterError):
    """A named socket does not exist on the target node."""


class AlreadyConnectedError(WriterError):
    """A target input socket already has a source connection."""


class NotConnectedError(WriterError):
    """``disconnect`` was asked to remove an edge that does not exist."""


class CycleError(WriterError):
    """The requested ``connect`` would introduce a cycle in the graph."""


class GroupError(WriterError):
    """``add_group`` was given an invalid set of node ids or empty input."""


class UnknownPropertyError(WriterError):
    """A property key passed to ``add_node`` does not exist on the
    node class. Sister to ``UnknownSocketError`` — same kind of typo
    catch, but for the ``properties`` dict instead of socket names.
    """


class DynamicInputError(WriterError):
    """A dynamic-input operation was attempted on an incompatible node."""


class NodeNotFoundError(WriterError):
    """A node id was not present in the graph."""


# ---------------------------------------------------------------------------
# Node metadata cache
# ---------------------------------------------------------------------------


class NodeMetadata(pydantic.BaseModel):
    """Static metadata for a registered node class, cached per process.

    ``inputs`` / ``outputs`` are socket names in declaration order (the
    ones the class sets up in ``setup()``, before any graph-specific
    dynamic inputs). ``properties`` is the tuple of class-declared
    property names (from ``instance.properties`` after ``setup()``).
    ``base_type`` is the class-level ``_base_type`` / ``base_type``
    computed field. ``is_dynamic`` is True when the class is a subclass
    of ``DynamicSocketNodeBase``.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    registry: str
    base_type: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    properties: tuple[str, ...]
    is_dynamic: bool


_METADATA_CACHE: dict[str, NodeMetadata] = {}


def _dynamic_socket_base_cls() -> type:
    from talemate.game.engine.nodes.core.dynamic import DynamicSocketNodeBase

    return DynamicSocketNodeBase


def get_node_metadata(registry: str) -> NodeMetadata:
    """Return cached ``NodeMetadata`` for a registry path.

    Raises ``UnknownRegistryError`` if the registry is not present in
    the live ``NODES`` dict.
    """

    cached = _METADATA_CACHE.get(registry)
    if cached is not None:
        return cached

    ensure_registry_loaded()
    from talemate.game.engine.nodes.registry import NODES

    node_cls = NODES.get(registry)
    if node_cls is None:
        raise UnknownRegistryError(
            f"Registry '{registry}' is not registered. "
            f"(Did you forget to call ensure_registry_loaded() or import "
            f"the module that declares it?)"
        )

    try:
        instance = node_cls()
    except Exception as exc:  # pragma: no cover - defensive
        raise UnknownRegistryError(
            f"Registry '{registry}' is registered but the class "
            f"({node_cls.__name__}) could not be instantiated: {exc}"
        ) from exc

    try:
        inputs = tuple(s.name for s in instance.inputs)
    except Exception:
        inputs = tuple()
    try:
        outputs = tuple(s.name for s in instance.outputs)
    except Exception:
        outputs = tuple()
    try:
        properties = tuple((instance.properties or {}).keys())
    except Exception:
        properties = tuple()

    base_type = ""
    try:
        base_type = instance.base_type  # computed_field on NodeBase
    except Exception:
        base_type = getattr(node_cls, "_base_type", "") or ""

    try:
        is_dynamic = isinstance(instance, _dynamic_socket_base_cls())
    except Exception:  # pragma: no cover - defensive
        is_dynamic = False

    meta = NodeMetadata(
        registry=registry,
        base_type=base_type or "",
        inputs=inputs,
        outputs=outputs,
        properties=properties,
        is_dynamic=is_dynamic,
    )
    _METADATA_CACHE[registry] = meta
    return meta


def clear_metadata_cache() -> None:
    """Flush the node-metadata cache.

    Called by the loader after registering scene-level modules so that
    their socket layouts are re-probed on next access. Also useful from
    tests that want to observe fresh probes.
    """

    _METADATA_CACHE.clear()


# ---------------------------------------------------------------------------
# Graph accessors
# ---------------------------------------------------------------------------


def _nodes(graph: dict) -> dict[str, dict]:
    nodes = graph.get("nodes")
    if nodes is None:
        nodes = {}
        graph["nodes"] = nodes
    return nodes


def _edges(graph: dict) -> dict[str, list[str]]:
    edges = graph.get("edges")
    if edges is None:
        edges = {}
        graph["edges"] = edges
    return edges


def _require_node(graph: dict, node_id: str) -> dict:
    nodes = _nodes(graph)
    if node_id not in nodes:
        raise NodeNotFoundError(f"Node id '{node_id}' is not in the graph")
    return nodes[node_id]


def _dynamic_input_names(node: dict) -> list[str]:
    return [d.get("name") for d in (node.get("dynamic_inputs") or []) if d.get("name")]


def _input_names_for_node(node: dict) -> list[str]:
    """Inputs = class-declared inputs plus any dynamic_inputs on this node.

    Duplicates are removed while preserving declaration order (class
    inputs first, then dynamic inputs).
    """

    registry = node.get("registry")
    static_inputs: tuple[str, ...] = tuple()
    if registry:
        try:
            static_inputs = get_node_metadata(registry).inputs
        except UnknownRegistryError:
            static_inputs = tuple()

    dyn = _dynamic_input_names(node)
    seen: set[str] = set()
    out: list[str] = []
    for name in list(static_inputs) + dyn:
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _output_names_for_node(node: dict) -> list[str]:
    registry = node.get("registry")
    if not registry:
        return []
    try:
        return list(get_node_metadata(registry).outputs)
    except UnknownRegistryError:
        return []


# ---------------------------------------------------------------------------
# Pure primitives
# ---------------------------------------------------------------------------


def add_node(
    graph: dict,
    registry: str,
    *,
    title: str | None = None,
    properties: dict[str, Any] | None = None,
    x: int = 0,
    y: int = 0,
    width: int = DEFAULT_NODE_WIDTH,
    height: int | None = None,
) -> str:
    """Add a new node to ``graph`` and return its new UUID.

    The new id is always a freshly generated ``uuid4``. The registry
    must be present in the live ``NODES`` dict, otherwise
    ``UnknownRegistryError`` is raised.

    Property keys in ``properties`` are validated against the node
    class's declared ``Fields`` — an unknown / typo'd key raises
    ``UnknownPropertyError`` with a helpful message listing the valid
    property names. This is the property-side equivalent of how
    ``connect()`` validates socket names.

    ``height`` defaults to ``None`` — the writer intentionally does not
    pin a height on new nodes because height should be estimated by
    the layout pass from the node's socket / property counts. Pass an
    explicit integer to override and pin the height.
    """

    meta = get_node_metadata(registry)

    # Validate property keys against the class metadata. We deliberately
    # validate even an empty/None properties arg early in the function
    # so the error fires before any partial mutation happens.
    if properties:
        valid = set(meta.properties)
        unknown = [k for k in properties if k not in valid]
        if unknown:
            unknown_repr = ", ".join(repr(k) for k in unknown)
            valid_repr = ", ".join(repr(k) for k in sorted(valid)) or "(none)"
            raise UnknownPropertyError(
                f"Node {registry!r} has no property/properties "
                f"{unknown_repr}. Valid properties: {valid_repr}."
            )

    new_id = str(uuid.uuid4())
    node: dict[str, Any] = {
        "title": title if title is not None else registry.split("/")[-1],
        "id": new_id,
        "properties": dict(properties or {}),
        "x": int(x),
        "y": int(y),
        "width": int(width),
        "collapsed": False,
        "inherited": False,
        "registry": registry,
        "base_type": meta.base_type,
    }
    if height is not None:
        node["height"] = int(height)
    if meta.is_dynamic:
        # Mirror the shape shipped graphs use: an empty list is valid and
        # makes future add_dynamic_input calls ergonomic.
        node["dynamic_inputs"] = []

    _nodes(graph)[new_id] = node
    return new_id


def remove_node(graph: dict, node_id: str) -> None:
    """Remove a node and sweep every edge that references it.

    The edge sweep removes:

    * any edge key whose source node is ``node_id``
    * any edge target entry whose target node is ``node_id``, pruning
      now-empty target lists (and therefore their edge keys)
    """

    nodes = _nodes(graph)
    if node_id not in nodes:
        raise NodeNotFoundError(f"Node id '{node_id}' is not in the graph")

    del nodes[node_id]

    edges = _edges(graph)
    # Drop entire edge keys whose source is this node
    to_drop = [src for src in edges if src.split(".", 1)[0] == node_id]
    for src in to_drop:
        del edges[src]

    # For remaining edges, filter out targets pointing at this node.
    empty_keys: list[str] = []
    for src, targets in edges.items():
        kept = [tgt for tgt in targets if tgt.split(".", 1)[0] != node_id]
        if len(kept) != len(targets):
            edges[src] = kept
        if not edges[src]:
            empty_keys.append(src)
    for key in empty_keys:
        del edges[key]


def _target_has_source(graph: dict, target_node: str, target_socket: str) -> bool:
    full_tgt = f"{target_node}.{target_socket}"
    for _src, targets in _edges(graph).items():
        if full_tgt in targets:
            return True
    return False


def connect(
    graph: dict,
    source_id: str,
    source_socket: str,
    target_id: str,
    target_socket: str,
) -> None:
    """Connect ``source_id.source_socket`` to ``target_id.target_socket``.

    Validates that:

    * both nodes exist in the graph
    * the source output socket exists on the source node's class
    * the target input socket exists (class-declared or dynamic) on the
      target node
    * the target input is not already connected (fan-in is at most 1)
    * adding the edge would not introduce a cycle

    On cycle detection the edge is rolled back before ``CycleError`` is
    raised.
    """

    source_node = _require_node(graph, source_id)
    target_node = _require_node(graph, target_id)

    source_outputs = _output_names_for_node(source_node)
    if source_socket not in source_outputs:
        raise UnknownSocketError(
            f"Source node {source_id} ({source_node.get('registry')}) has no "
            f"output socket '{source_socket}'. Known outputs: "
            f"{source_outputs or '(none)'}"
        )

    target_inputs = _input_names_for_node(target_node)
    if target_socket not in target_inputs:
        raise UnknownSocketError(
            f"Target node {target_id} ({target_node.get('registry')}) has no "
            f"input socket '{target_socket}'. Known inputs: "
            f"{target_inputs or '(none)'}"
        )

    if _target_has_source(graph, target_id, target_socket):
        raise AlreadyConnectedError(
            f"Target input {target_id}.{target_socket} is already connected. "
            f"Disconnect the existing source before reassigning."
        )

    edges = _edges(graph)
    src_key = f"{source_id}.{source_socket}"
    tgt_value = f"{target_id}.{target_socket}"

    targets_list = edges.setdefault(src_key, [])
    targets_list.append(tgt_value)

    # Cycle check AFTER adding, so we include the new edge; roll back if
    # it would form a cycle.
    if _would_cycle_including_new(graph, source_id, target_id):
        targets_list.remove(tgt_value)
        if not targets_list:
            del edges[src_key]
        raise CycleError(
            f"Connecting {source_id}.{source_socket} -> "
            f"{target_id}.{target_socket} would introduce a cycle."
        )


def _would_cycle_including_new(graph: dict, source_node: str, target_node: str) -> bool:
    """Cycle check based on current edge state (edge already inserted).

    With the new edge in place, a cycle exists iff there is a path from
    ``target_node`` back to ``source_node`` (counting the new edge as
    part of adjacency). Self-loops are cycles.
    """

    if source_node == target_node:
        return True

    # Build node-level adjacency from every current edge. Edges are
    # ``<node_id>.<socket>`` strings; we only care about the node halves.
    adj: dict[str, set[str]] = {}
    for src, targets in _edges(graph).items():
        s_node = src.split(".", 1)[0]
        for tgt in targets:
            t_node = tgt.split(".", 1)[0]
            adj.setdefault(s_node, set()).add(t_node)

    # Walk forward from target_node; if we reach source_node we have a
    # cycle because source -> ... -> target -> source.
    stack = list(adj.get(target_node, ()))
    seen: set[str] = set()
    while stack:
        current = stack.pop()
        if current == source_node:
            return True
        if current in seen:
            continue
        seen.add(current)
        stack.extend(adj.get(current, ()))
    return False


def disconnect(
    graph: dict,
    source_id: str,
    source_socket: str,
    target_id: str,
    target_socket: str,
) -> None:
    """Remove the edge ``source_id.source_socket -> target_id.target_socket``.

    Raises ``NotConnectedError`` if the edge is not present.
    """

    edges = _edges(graph)
    src_key = f"{source_id}.{source_socket}"
    tgt_value = f"{target_id}.{target_socket}"

    targets = edges.get(src_key)
    if not targets or tgt_value not in targets:
        raise NotConnectedError(
            f"No edge {source_id}.{source_socket} -> "
            f"{target_id}.{target_socket} to remove."
        )
    targets.remove(tgt_value)
    if not targets:
        del edges[src_key]


def add_dynamic_input(
    graph: dict,
    node_id: str,
    name: str,
    socket_type: str = "*",
) -> None:
    """Append a ``dynamic_inputs`` entry on a ``DynamicSocketNodeBase`` node.

    Raises ``DynamicInputError`` if the node's registered class is not a
    subclass of ``DynamicSocketNodeBase``, or if a dynamic input with
    ``name`` already exists.

    The default ``socket_type`` is ``"*"`` — the LiteGraph **wildcard**
    socket type that accepts a connection from any other socket regardless
    of type. This is the correct default for collector-style nodes like
    ``data/DictCollector``, ``data/ListCollector``, ``data/string/AdvancedFormat``,
    and ``data/string/Jinja2Format``, which all want to accept inputs of
    any type. **Do NOT use ``"any"`` as the type** — despite the name,
    ``"any"`` is a specific named type in LiteGraph, not a wildcard, and
    the frontend's socket validation refuses to connect a typed output
    (e.g. ``int``, ``str``) to an ``"any"`` input. Only use ``"*"``.
    """

    node = _require_node(graph, node_id)
    registry = node.get("registry")
    if not registry:
        raise DynamicInputError(
            f"Node {node_id} has no registry; cannot determine whether it "
            f"supports dynamic inputs."
        )

    meta = get_node_metadata(registry)
    if not meta.is_dynamic:
        raise DynamicInputError(
            f"Node {node_id} ({registry}) is not a DynamicSocketNodeBase "
            f"subclass; it does not accept dynamic inputs."
        )

    dyn = node.setdefault("dynamic_inputs", [])
    if any(d.get("name") == name for d in dyn):
        raise DynamicInputError(
            f"Dynamic input '{name}' already exists on node {node_id}."
        )
    dyn.append({"name": name, "type": socket_type})


def remove_dynamic_input(graph: dict, node_id: str, name: str) -> None:
    """Remove a dynamic input entry and sweep any edges using it."""

    node = _require_node(graph, node_id)
    dyn = node.get("dynamic_inputs") or []
    new_dyn = [d for d in dyn if d.get("name") != name]
    if len(new_dyn) == len(dyn):
        raise DynamicInputError(f"No dynamic input named '{name}' on node {node_id}.")
    node["dynamic_inputs"] = new_dyn

    # Sweep any edges targeting this now-removed socket.
    edges = _edges(graph)
    tgt_value = f"{node_id}.{name}"
    empty_keys: list[str] = []
    for src, targets in edges.items():
        if tgt_value in targets:
            targets.remove(tgt_value)
        if not targets:
            empty_keys.append(src)
    for key in empty_keys:
        del edges[key]


# ---------------------------------------------------------------------------
# Group creation
# ---------------------------------------------------------------------------


def add_group(
    graph: dict,
    title: str,
    color: str,
    node_ids: Iterable[str],
    *,
    font_size: int = GROUP_DEFAULT_FONT_SIZE,
) -> dict:
    """Append a colored, titled group around the given nodes' bounding box.

    Computes the union bounding box of every node in ``node_ids`` (using
    each node's ``x``/``y``/``width``/``height``) and then expands it by
    the same padding constants the frontend's "Create Group from
    Selection" menu uses, so the resulting group is visually identical
    to a user-created one.

    Parameters
    ----------
    graph:
        The graph dict being mutated.
    title:
        Display title for the group. Use a short human-readable label
        (e.g. ``"Input"``, ``"Stage 0"``, ``"Output"``).
    color:
        The group's border / title color, as a hex string. Use one of
        the constants on :class:`GroupColor` to match the frontend's
        preset palette.
    node_ids:
        The nodes the group should encompass. Must contain at least one
        valid node id. Short-prefix ids are NOT resolved here — pass
        full ids (use ``GraphWriter.add_group`` for prefix support).
    font_size:
        Title font size. Defaults to 24, which matches every existing
        group in shipped graphs.

    Returns
    -------
    dict
        The newly-created group dict (which has also been appended to
        ``graph["groups"]`` in place). Caller can mutate further if
        needed.

    Raises
    ------
    GroupError
        If ``node_ids`` is empty or any id does not exist in the graph.

    Notes
    -----
    Call this **after** running ``layout_graph``. Group bounding boxes
    are computed from the nodes' actual positions, so positioning the
    nodes first is required.
    """

    nodes = _nodes(graph)
    ids = list(node_ids)
    if not ids:
        raise GroupError("add_group requires at least one node id.")

    rects: list[tuple[int, int, int, int]] = []
    for nid in ids:
        node = nodes.get(nid)
        if node is None:
            raise GroupError(f"add_group: unknown node id {nid!r}.")
        x = int(node.get("x", 0) or 0)
        y = int(node.get("y", 0) or 0)
        w = int(node.get("width", DEFAULT_NODE_WIDTH) or DEFAULT_NODE_WIDTH)
        h = int(node.get("height", DEFAULT_NODE_HEIGHT) or DEFAULT_NODE_HEIGHT)
        rects.append((x, y, w, h))

    min_x = min(r[0] for r in rects)
    min_y = min(r[1] for r in rects)
    max_x = max(r[0] + r[2] for r in rects)
    max_y = max(r[1] + r[3] for r in rects)

    # Mirror the frontend's group-creation padding (groupInteractions.js).
    pos_x = min_x - GROUP_PADDING
    pos_y = min_y - GROUP_TOP_PADDING - GROUP_TITLE_HEIGHT
    raw_width = (max_x - min_x) + GROUP_PADDING * 2
    raw_height = (
        (max_y - min_y) + GROUP_PADDING + GROUP_TOP_PADDING + GROUP_TITLE_HEIGHT
    )
    width = max(GROUP_MIN_WIDTH, raw_width)
    height = max(GROUP_MIN_HEIGHT, raw_height)

    group_dict = {
        "title": title,
        "x": pos_x,
        "y": pos_y,
        "width": width,
        "height": height,
        "color": color,
        "font_size": font_size,
        "inherited": False,
    }

    groups = graph.setdefault("groups", [])
    groups.append(group_dict)
    return group_dict


# ---------------------------------------------------------------------------
# GraphWriter ergonomics
# ---------------------------------------------------------------------------


class GraphWriter:
    """Ergonomic wrapper around the pure mutation primitives.

    Holds a graph dict plus an optional source path for ``save()``. All
    mutation methods delegate to the module-level functions above — the
    class is sugar, not logic.
    """

    def __init__(self, graph: dict, *, path: str | Path | None = None) -> None:
        self.graph = graph
        self.path: Path | None = Path(path) if path is not None else None

    # -- construction ------------------------------------------------------

    @classmethod
    def load(
        cls,
        path: str | Path,
        *,
        extra_module_paths: Iterable[str | Path] | None = None,
    ) -> "GraphWriter":
        """Load a graph JSON file from disk and wrap it.

        If ``path`` lives under ``scenes/<name>/nodes/``, sibling JSON
        modules in that directory are auto-registered into the live
        ``NODES`` dict so the writer can introspect them when you
        reference one via ``add_node("...")``. Pass ``extra_module_paths``
        to also walk additional directories — useful for non-standard
        layouts where related modules live elsewhere.
        """

        graph = load_graph(path, extra_module_paths=extra_module_paths)
        return cls(graph, path=path)

    def save(self, path: str | Path | None = None, *, indent: int = 2) -> Path:
        """Persist the graph to disk, returning the path written to.

        If ``path`` is omitted the writer uses the path it was loaded
        from; if the writer was constructed without a path and no
        argument is passed this raises ``WriterError``.
        """

        target = Path(path) if path is not None else self.path
        if target is None:
            raise WriterError(
                "GraphWriter.save() needs an explicit path because this "
                "writer was not constructed via GraphWriter.load()."
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as fh:
            json.dump(self.graph, fh, indent=indent)
            fh.write("\n")
        self.path = target
        return target

    # -- mutation ----------------------------------------------------------

    def add_node(
        self,
        registry: str,
        *,
        title: str | None = None,
        properties: dict[str, Any] | None = None,
        x: int = 0,
        y: int = 0,
        width: int = DEFAULT_NODE_WIDTH,
        height: int | None = None,
    ) -> str:
        return add_node(
            self.graph,
            registry,
            title=title,
            properties=properties,
            x=x,
            y=y,
            width=width,
            height=height,
        )

    def remove_node(self, node_id: str) -> None:
        remove_node(self.graph, self._resolve(node_id))

    def connect(self, *args: str) -> None:
        """Connect two sockets.

        Two call shapes are supported:

        * ``writer.connect(src_id, src_socket, tgt_id, tgt_socket)``
        * ``writer.connect("<src_id>.<src_socket>", "<tgt_id>.<tgt_socket>")``
        """

        src_id, src_socket, tgt_id, tgt_socket = self._parse_edge_args(args)
        connect(
            self.graph,
            self._resolve(src_id),
            src_socket,
            self._resolve(tgt_id),
            tgt_socket,
        )

    def disconnect(self, *args: str) -> None:
        """Disconnect two sockets. Same call shapes as :meth:`connect`."""

        src_id, src_socket, tgt_id, tgt_socket = self._parse_edge_args(args)
        disconnect(
            self.graph,
            self._resolve(src_id),
            src_socket,
            self._resolve(tgt_id),
            tgt_socket,
        )

    def add_dynamic_input(
        self, node_id: str, name: str, socket_type: str = "*"
    ) -> None:
        add_dynamic_input(
            self.graph, self._resolve(node_id), name, socket_type=socket_type
        )

    def remove_dynamic_input(self, node_id: str, name: str) -> None:
        remove_dynamic_input(self.graph, self._resolve(node_id), name)

    def add_group(
        self,
        title: str,
        color: str,
        node_ids: Iterable[str],
        *,
        font_size: int = GROUP_DEFAULT_FONT_SIZE,
    ) -> dict:
        """Append a colored, titled group around the given nodes.

        Same as the pure :func:`add_group` but resolves short-prefix
        node ids transparently. **Call this after layout** — group
        bounding boxes are computed from the nodes' actual positions.

        Pick a ``color`` from :class:`GroupColor` (or pass a literal hex
        string). The agent decides which color matches the cluster's
        purpose; common conventions:

        * ``GroupColor.INPUT`` for input-collection / passthrough bands
        * ``GroupColor.OUTPUT`` for output-emission bands
        * ``GroupColor.PROCESS`` for main computation stages
        * ``GroupColor.VALIDATION`` for guard / validation chains
        * ``GroupColor.SPECIAL`` for helpers and one-offs
        """

        resolved = [self._resolve(nid) for nid in node_ids]
        return add_group(
            self.graph,
            title=title,
            color=color,
            node_ids=resolved,
            font_size=font_size,
        )

    # -- lookup helpers ----------------------------------------------------

    def resolve(self, node_id_or_prefix: str) -> str:
        """Resolve a short-prefix node id to a full id."""

        return self._resolve(node_id_or_prefix)

    def _resolve(self, node_id_or_prefix: str) -> str:
        try:
            return resolve_node_id(self.graph, node_id_or_prefix)
        except ValueError as exc:
            raise NodeNotFoundError(str(exc)) from exc

    @staticmethod
    def _parse_edge_args(
        args: tuple[str, ...],
    ) -> tuple[str, str, str, str]:
        if len(args) == 4:
            return args  # type: ignore[return-value]
        if len(args) == 2:
            src_node, src_socket = split_socket_path(args[0])
            tgt_node, tgt_socket = split_socket_path(args[1])
            return src_node, src_socket, tgt_node, tgt_socket
        raise TypeError(
            "connect/disconnect expects either 4 string args "
            "(src_id, src_socket, tgt_id, tgt_socket) or 2 dotted strings "
            "('src_id.socket', 'tgt_id.socket')."
        )

    # -- introspection -----------------------------------------------------

    def summarize(self) -> analysis.GraphSummary:
        return analysis.summarize(self.graph)
