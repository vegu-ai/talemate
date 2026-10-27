"""
Compatibility of a template override with the shipped default.

Markers are read from the shipped default with Jinja's parser and checked
against the override; nothing is listed per template:

- extractor: a key the default declares with a template extractor setter
- anchor: a response marker the code's extractors parse for that the default
  asks the model to write
- contract: a call on a context value that code declares it enforces
  (`talemate.prompts.contracts`) and that the default makes
- include: a partial the default includes
- flag: a context variable the default tests in an ``if``

A missing extractor, anchor or contract breaks the result (incompatible); a missing
include or flag drops a section of the prompt (incomplete).
"""

from __future__ import annotations

import functools
import inspect
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

import jinja2
import structlog
from jinja2 import nodes
from pydantic import BaseModel

from talemate.prompts.base import TEMPLATE_EXTRACTOR_SETTERS, Prompt
from talemate.prompts.contracts import template_contracts
from talemate.prompts.extensions import CaptureContextExtension
from talemate.prompts.groups import (
    Compatibility,
    CompatibilityReport,
    MissingMarker,
    TemplateInfo,
    get_default_template_path,
    get_group_template_path,
    get_scene_template_path,
    identify_template_file,
    resolve_template,
)
from talemate.prompts.response import Extractor, ResponseSpec

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = [
    "OverrideStatus",
    "RenderedOverride",
    "rendered_overrides",
    "response_anchors",
    "check_override",
    "override_status",
    "log_override_status",
]

log = structlog.get_logger("talemate.prompts.compatibility")

BREAKING_KINDS: frozenset[str] = frozenset({"extractor", "anchor", "contract"})

# names Jinja binds itself inside loops and call blocks
_IMPLICIT_NAMES = frozenset({"loop", "caller", "varargs", "kwargs"})

# setter arguments that hold the opening marker the extractor looks for
_SETTER_ANCHOR_ARGS = ("left", "start")

_parse_env = jinja2.Environment(extensions=[CaptureContextExtension])
_markers_cache: dict[tuple[str, float], "_TemplateMarkers | None"] = {}


class _Setter(BaseModel):
    """One extractor setter call: a constant anchor, as-is, or neither (unknown)."""

    key: str
    anchor: str | None = None
    as_is: bool = False


class _TemplateMarkers(BaseModel):
    text: str
    includes: list[str] = []
    extractor_keys: list[str] = []
    # in document order
    setters: list[_Setter] = []
    flags: list[str] = []
    names: list[str] = []
    # `name.attribute` reads on context values
    attribute_reads: list[str] = []


class _Reach(BaseModel):
    """A template together with every partial it reaches."""

    includes: set[str] = set()
    extractor_keys: set[str] = set()
    # extractor key -> one list per reached file of that file's setters for the key
    setters: dict[str, list[list[_Setter]]] = {}
    names: set[str] = set()
    attribute_reads: set[str] = set()
    text: str = ""

    def add_setters(self, setters: list[_Setter]) -> None:
        by_key: dict[str, list[_Setter]] = {}
        for setter in setters:
            by_key.setdefault(setter.key, []).append(setter)
        for key, file_setters in by_key.items():
            self.setters.setdefault(key, []).append(file_setters)

    def constant_anchors(self) -> dict[str, set[str]]:
        anchors: dict[str, set[str]] = {}
        for key, files in self.setters.items():
            for file_setters in files:
                anchors.setdefault(key, set()).update(
                    setter.anchor for setter in file_setters if setter.anchor
                )
        return anchors


def response_anchors() -> dict[str, frozenset[str]]:
    """
    Opening markers of every extractor held at module level by a loaded
    talemate module, directly or inside a ResponseSpec, each with the response
    keys it is extracted for.
    """
    owners: dict[str, set[str]] = {}
    for module_name, module in list(sys.modules.items()):
        if module is None or not module_name.startswith("talemate."):
            continue
        for value in list(vars(module).values()):
            if isinstance(value, ResponseSpec):
                for key, extractor in value.extractors.items():
                    for anchor in extractor.anchors():
                        owners.setdefault(anchor, set()).add(key)
            elif isinstance(value, Extractor):
                for anchor in value.anchors():
                    owners.setdefault(anchor, set())
    return {
        anchor: frozenset(keys) for anchor, keys in owners.items() if anchor.strip()
    }


@functools.cache
def _template_globals() -> frozenset[str]:
    env = jinja2.Environment()
    Prompt(uid="", agent_type="", name="").register_template_globals(env)
    return frozenset(env.globals)


@functools.cache
def _setter_signature(setter: str) -> inspect.Signature:
    return inspect.signature(getattr(Prompt, setter))


def _const_str(node: nodes.Node | None) -> str | None:
    if isinstance(node, nodes.Const) and isinstance(node.value, str):
        return node.value
    return None


def _setter_arguments(call: nodes.Call) -> dict[str, nodes.Node] | None:
    if not (
        isinstance(call.node, nodes.Name)
        and call.node.name in TEMPLATE_EXTRACTOR_SETTERS
    ):
        return None
    keywords = {keyword.key: keyword.value for keyword in call.kwargs}
    try:
        bound = _setter_signature(call.node.name).bind_partial(
            None, *call.args, **keywords
        )
    except TypeError:
        return None
    return bound.arguments


def _stored_names(node: nodes.Node) -> set[str]:
    names = {name.name for name in node.find_all(nodes.Name)}
    if isinstance(node, nodes.Name):
        names.add(node.name)
    return names


def _loaded_names(node: nodes.Node) -> list[str]:
    names = [name.name for name in node.find_all(nodes.Name) if name.ctx == "load"]
    if isinstance(node, nodes.Name) and node.ctx == "load":
        names.insert(0, node.name)
    return names


def _used_names(ast: nodes.Template) -> list[str]:
    """Names the template reads, except reads that only feed `set x = x | ...`."""
    rebinding_reads: set[int] = set()
    for node in ast.find_all(nodes.Assign):
        targets = _stored_names(node.target)
        rebinding_reads.update(
            id(name)
            for name in node.node.find_all(nodes.Name)
            if name.ctx == "load" and name.name in targets
        )
        if isinstance(node.node, nodes.Name) and node.node.name in targets:
            rebinding_reads.add(id(node.node))
    return [
        name.name
        for name in ast.find_all(nodes.Name)
        if name.ctx == "load" and id(name) not in rebinding_reads
    ]


def _plain_assignments(ast: nodes.Template) -> set[str]:
    """Names set in the template; `set x = x | ...` still reads x from the context."""
    assigned: set[str] = set()
    for node in ast.find_all(nodes.Assign):
        targets = _stored_names(node.target)
        assigned |= targets - set(_loaded_names(node.node))
    for node in ast.find_all(nodes.AssignBlock):
        assigned |= _stored_names(node.target)
    return assigned


def _flags(ast: nodes.Template, excluded: frozenset[str]) -> list[str]:
    """Context names read in if tests, with loop, macro and with bindings scoped to their bodies."""
    flags: list[str] = []

    def visit(node: nodes.Node, bound: frozenset[str]) -> None:
        if isinstance(node, (nodes.If, nodes.CondExpr)):
            flags.extend(n for n in _loaded_names(node.test) if n not in bound)
        if isinstance(node, nodes.For):
            visit(node.iter, bound)
            inner = bound | _stored_names(node.target) | {"loop"}
            for child in node.body:
                visit(child, inner)
            if node.test is not None:
                visit(node.test, inner)
            for child in node.else_:
                visit(child, bound)
            return
        if isinstance(node, (nodes.Macro, nodes.CallBlock)):
            if isinstance(node, nodes.CallBlock):
                visit(node.call, bound)
            for default in node.defaults:
                visit(default, bound)
            inner = bound | {arg.name for arg in node.args} | _IMPLICIT_NAMES
            for child in node.body:
                visit(child, inner)
            return
        if isinstance(node, nodes.With):
            for value in node.values:
                visit(value, bound)
            inner = bound | set().union(*(_stored_names(t) for t in node.targets))
            for child in node.body:
                visit(child, inner)
            return
        for child in node.iter_child_nodes():
            visit(child, bound)

    visit(ast, excluded | _plain_assignments(ast))
    return flags


def _read_markers(source: str, env_globals: frozenset[str]) -> _TemplateMarkers | None:
    try:
        ast = _parse_env.parse(source)
    except jinja2.TemplateSyntaxError:
        return None

    includes = []
    for node in ast.find_all(
        (nodes.Include, nodes.Import, nodes.FromImport, nodes.Extends)
    ):
        name = _const_str(node.template)
        if name:
            includes.append(name)

    extractor_keys = []
    setters: list[_Setter] = []
    setter_consts: set[int] = set()
    for call in ast.find_all(nodes.Call):
        arguments = _setter_arguments(call)
        if arguments is None:
            continue
        setter_consts.update(id(const) for const in call.find_all(nodes.Const))
        key = _const_str(arguments.get("name"))
        if not key:
            continue
        extractor_keys.append(key)
        anchor = None
        for argument in _SETTER_ANCHOR_ARGS:
            value = _const_str(arguments.get(argument))
            if value and value.strip():
                anchor = value
                break
        setters.append(
            _Setter(
                key=key,
                anchor=anchor,
                as_is=call.node.name == "set_as_is_extractor",
            )
        )

    flags = _flags(ast, env_globals | _IMPLICIT_NAMES)
    names = _used_names(ast)
    attribute_reads = [
        f"{node.node.name}.{node.attr}"
        for node in ast.find_all(nodes.Getattr)
        if isinstance(node.node, nodes.Name) and node.node.ctx == "load"
    ]

    # what the template says to the model: its text and string constants, without
    # comments and without the arguments of extractor setters
    text = [data.data for data in ast.find_all(nodes.TemplateData)]
    text.extend(
        const.value
        for const in ast.find_all(nodes.Const)
        if isinstance(const.value, str) and id(const) not in setter_consts
    )

    return _TemplateMarkers(
        text="\n".join(text),
        includes=list(dict.fromkeys(includes)),
        extractor_keys=list(dict.fromkeys(extractor_keys)),
        setters=setters,
        flags=list(dict.fromkeys(flags)),
        names=list(dict.fromkeys(names)),
        attribute_reads=list(dict.fromkeys(attribute_reads)),
    )


def _markers(path: Path, env_globals: frozenset[str]) -> _TemplateMarkers | None:
    """None for a file that cannot be read, decoded or parsed; such a file fails when it is rendered."""
    try:
        key = (str(path.resolve()), path.stat().st_mtime)
        if key not in _markers_cache:
            _markers_cache[key] = _read_markers(
                path.read_text(encoding="utf-8"), env_globals
            )
    except (OSError, UnicodeDecodeError):
        return None
    return _markers_cache[key]


def _partial_path(env: jinja2.Environment, name: str) -> Path | None:
    try:
        _, filename, _ = env.loader.get_source(env, name)
    except (jinja2.TemplateNotFound, OSError, UnicodeDecodeError):
        return None
    return Path(filename) if filename else None


def _expand(
    root: _TemplateMarkers, env: jinja2.Environment, env_globals: frozenset[str]
) -> _Reach:
    """Follow partials the way the renderer resolves them."""
    reach = _Reach(
        extractor_keys=set(root.extractor_keys),
        names=set(root.names),
        attribute_reads=set(root.attribute_reads),
    )
    reach.add_setters(root.setters)
    texts = [root.text]
    pending = list(root.includes)
    while pending:
        name = pending.pop()
        if name in reach.includes:
            continue
        reach.includes.add(name)
        path = _partial_path(env, name)
        partial = _markers(path, env_globals) if path else None
        if partial is None:
            continue
        reach.extractor_keys.update(partial.extractor_keys)
        reach.add_setters(partial.setters)
        reach.names.update(partial.names)
        reach.attribute_reads.update(partial.attribute_reads)
        texts.append(partial.text)
        pending.extend(partial.includes)
    reach.text = "\n".join(texts)
    return reach


def check_override(
    agent: str,
    override_path: Path,
    default_path: Path,
    anchors: Mapping[str, frozenset[str]] | None = None,
) -> CompatibilityReport:
    """
    Compare an override with the shipped default it replaces. An override that
    does not parse is left to the renderer, which reports it when it is used.
    """
    env_globals = _template_globals()
    default = _markers(default_path, env_globals)
    override = _markers(override_path, env_globals)
    if default is None or override is None:
        return CompatibilityReport()

    env = Prompt(uid="", agent_type=agent, name="").template_env()
    default_reach = _expand(default, env, env_globals)
    override_reach = _expand(override, env, env_globals)

    missing: list[MissingMarker] = []

    for key in sorted(default_reach.extractor_keys - override_reach.extractor_keys):
        missing.append(MissingMarker(kind="extractor", name=key))

    if anchors is None:
        anchors = response_anchors()
    owners: dict[str, set[str]] = {
        anchor: set(keys) for anchor, keys in anchors.items()
    }
    for key, key_anchors in default_reach.constant_anchors().items():
        for anchor in key_anchors:
            owners.setdefault(anchor, set()).add(key)

    default_lower = default_reach.text.lower()
    override_lower = override_reach.text.lower()

    def extracted_differently(keys: set[str]) -> bool:
        # the override's own extractor for the key replaces the code's one at send
        # time; the last setter call wins, which is only knowable within one file
        for key in keys:
            files = override_reach.setters.get(key, [])
            if len(files) != 1:
                continue
            effective = files[0][-1]
            if effective.as_is:
                return True
            if effective.anchor and effective.anchor.lower() in override_lower:
                return True
        return False

    for anchor in sorted(owners):
        needle = anchor.lower()
        if needle not in default_lower or needle in override_lower:
            continue
        if extracted_differently(owners[anchor]):
            continue
        missing.append(MissingMarker(kind="anchor", name=anchor))

    contract_names: set[str] = set()
    for contract in template_contracts():
        if (
            contract.call in default_reach.attribute_reads
            and contract.call not in override_reach.attribute_reads
        ):
            missing.append(
                MissingMarker(
                    kind="contract", name=contract.call, detail=contract.reason
                )
            )
            contract_names.add(contract.call.split(".", 1)[0])

    for include in default.includes:
        if include not in override_reach.includes:
            missing.append(MissingMarker(kind="include", name=include))

    for flag in default.flags:
        if flag not in override_reach.names and flag not in contract_names:
            missing.append(MissingMarker(kind="flag", name=flag))

    if any(marker.kind in BREAKING_KINDS for marker in missing):
        compatibility: Compatibility = "incompatible"
    elif missing:
        compatibility = "incomplete"
    else:
        compatibility = "compatible"

    return CompatibilityReport(compatibility=compatibility, missing_markers=missing)


class RenderedOverride(BaseModel):
    uid: str
    group: str
    compatibility: Compatibility = "compatible"
    missing_markers: list[MissingMarker] = []


def rendered_overrides(
    files: list[str], scene: "Scene | None" = None, agent: str | None = None
) -> list[RenderedOverride]:
    """
    The override files among the files a render loaded, each with its report.
    `agent` is the rendered prompt's agent, used for flat scene templates.
    """
    overrides = []
    anchors = None
    for file in files:
        identified = identify_template_file(file, scene, flat_agent=agent)
        if identified is None or identified[0] == "default":
            continue
        group, template_agent, name = identified
        default_path = get_default_template_path(template_agent, name)
        if not default_path.exists():
            continue
        if anchors is None:
            anchors = response_anchors()
        report = check_override(template_agent, Path(file), default_path, anchors)
        overrides.append(
            RenderedOverride(
                uid=f"{template_agent}.{name}",
                group=group,
                compatibility=report.compatibility,
                missing_markers=report.missing_markers,
            )
        )
    return overrides


class OverrideStatus(BaseModel):
    has_default: bool = False
    # group that serves the template once this copy is removed
    fallback_group: str | None = None
    is_outdated: bool = False
    compatibility: Compatibility = "compatible"
    missing_markers: list[MissingMarker] = []


def override_status(
    group: str,
    agent: str,
    template_name: str,
    scene: "Scene | None" = None,
    anchors: Mapping[str, frozenset[str]] | None = None,
) -> OverrideStatus:
    """Status of one group's copy of a template against the shipped default."""
    default_path = get_default_template_path(agent, template_name)
    if group == "default" or not default_path.exists():
        return OverrideStatus()

    if group == "scene":
        override_path = (
            get_scene_template_path(scene, agent, template_name) if scene else None
        )
    else:
        override_path = get_group_template_path(group, agent, template_name)

    if override_path is None or not override_path.exists():
        return OverrideStatus(has_default=True)

    _, fallback_group = resolve_template(
        agent, template_name, scene, exclude_group=group
    )
    report = check_override(agent, override_path, default_path, anchors)
    return OverrideStatus(
        has_default=True,
        fallback_group=fallback_group,
        is_outdated=override_path.stat().st_mtime < default_path.stat().st_mtime,
        compatibility=report.compatibility,
        missing_markers=report.missing_markers,
    )


def log_override_status(templates: list[TemplateInfo]) -> None:
    for template in templates:
        if template.compatibility != "compatible":
            log.warning(
                f"{template.compatibility.capitalize()} template override",
                template=template.uid,
                group=template.source_group,
                missing=[
                    f"{marker.kind} {marker.name}"
                    + (f" ({marker.detail})" if marker.detail else "")
                    for marker in template.missing_markers
                ],
            )
        elif template.is_outdated:
            log.info(
                "Outdated template override",
                template=template.uid,
                group=template.source_group,
            )
