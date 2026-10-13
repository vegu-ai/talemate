import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import jinja2
import pytest
from jinja2 import meta

import talemate.prompts
from talemate.decisions.gate import decision_gate
from talemate.prompts.extensions import CaptureContextExtension

from test_editor_decision_checks import editor_case, revise, scoped_check  # noqa: F401

GOLDEN = Path(__file__).parents[1] / "data/decisions/template-golden.json"
LOCK = Path(tempfile.gettempdir()) / "talemate-decision-golden.lock"
TEMPLATES = Path(talemate.prompts.__file__).parent / "templates"

# Decision templates that are not policies: other templates include or import
# them, so they never render a decision request of their own.
HELPER_TEMPLATES = {
    "common/decision-character-references.jinja2",
    "common/decision-check-macros.jinja2",
    "common/decision-visual-selection.jinja2",
    "editor/decision-findings.jinja2",
}
EDITOR_UID = "editor.decision-checks"


def noul(p):
    return {"type": "noul", "p_true": p}


def choice(selected, confidence, keys):
    rest = (1 - 0.98) / (len(keys) - 1)
    return {
        "type": "choice",
        "selected": selected,
        "probabilities": {key: 0.98 if key == selected else rest for key in keys},
        "confidence": confidence,
    }


CHARACTERS = [
    {"name": "Mara", "aliases": ["Mara", "the captain"], "description": "A sailor."},
    {"name": "Ilse", "aliases": ["Ilse"], "description": "A lighthouse keeper."},
    {"name": "Oren", "aliases": ["Oren"], "description": ""},
]
PINS = {
    "door": {"condition": "Is the door open?", "state": False},
    "sleep": {"condition": "Is anybody asleep?", "state": True},
    "rain": {"condition": "Is it raining?", "state": None},
}
ASSETS = {
    "harbour-day": {"name": "Harbour day", "tags": ["harbour", "day"]},
    "harbour-night": {"name": None, "tags": ["harbour", "night"]},
}
CHOICE_KEYS = ["none", *ASSETS]


def visual_cases(kind, current_key, uid):
    slot = "avatar" if kind == "portrait" else "background"

    def state(current):
        base = {"content": "Dawn breaks over the harbour."}
        if kind == "portrait":
            base["character"] = "Mara"
        return {
            **base,
            current_key: {"id": current, **ASSETS[current]} if current else None,
        }

    def case(name, current, fits, selected, confidence):
        return (
            f"{slot}-{name}",
            uid,
            {slot: list(ASSETS)},
            {"state": state(current), "assets": ASSETS},
            {
                "fits_current": noul(fits),
                slot: choice(selected, confidence, CHOICE_KEYS),
            },
        )

    return [
        case("keep", "harbour-day", 0.95, "harbour-night", 0.99),
        case("switch", "harbour-day", 0.1, "harbour-night", 0.95),
        case("uncertain", "harbour-day", 0.5, "harbour-night", 0.5),
        case("none", "harbour-day", 0.1, "none", 0.99),
        case("fits-without-current", None, 0.99, "harbour-night", 0.5),
        case("at-threshold", None, 0.1, "harbour-day", 0.9),
        case("keep-at-threshold", "harbour-day", 0.9, "harbour-night", 0.5),
    ]


def reference_case(name, uid, probabilities):
    return (
        name,
        uid,
        {c["name"]: [True, False] for c in CHARACTERS},
        {"state": "The captain waved.", "characters": CHARACTERS},
        {key: noul(p) for key, p in probabilities.items()},
    )


GATE_CASES = [
    *[
        (
            f"query-{p}",
            "world_state.decision-query",
            {"query": [True, False]},
            {"query": "Is the door open?", "state": "The door is open."},
            {"query": noul(p)},
        )
        for p in (0.95, 0.9, 0.05, 0.1, 0.5)
    ],
    (
        "pins",
        "world_state.decision-pin-conditions",
        {key: [True, False] for key in PINS},
        {
            "pins": PINS,
            "state": {
                "history": ["The door opens.", "Nobody is asleep."],
                "previous_states": {key: pin["state"] for key, pin in PINS.items()},
            },
        },
        {"door": noul(0.95), "sleep": noul(0.05), "rain": noul(0.5)},
    ),
    *[
        (
            f"reinforcement-{p}",
            "world_state.decision-reinforcement",
            {"state": [False]},
            {
                "state": {
                    "question": "Where is Mara?",
                    "character": "Mara",
                    "instructions": "One line.",
                    "previous_answer": "On deck.",
                    "last_updated_ts": "PT1H",
                    "current_ts": "PT2H",
                    "context": "Mara is on deck.",
                }
            },
            {"changed": noul(p)},
        )
        for p in (0.05, 0.1, 0.95, 0.5)
    ],
    reference_case(
        "entity-references",
        "memory.decision-entity-references",
        {"Mara": 0.95, "Ilse": 0.05, "Oren": 0.5},
    ),
    reference_case(
        "snapshot-references",
        "world_state.decision-snapshot-references",
        {"Mara": 0.9, "Ilse": 0.1, "Oren": 0.89},
    ),
    *visual_cases("portrait", "current_avatar", "world_state.decision-avatar"),
    *visual_cases(
        "background", "current_background", "world_state.decision-background"
    ),
]


def trace(service, result):
    def outcomes(entries):
        # the Decision Log lists details in recorded order
        return [{**entry, "detail_order": list(entry["details"])} for entry in entries]

    def action(entry):
        return entry.model_dump(
            mode="json",
            include={"action", "status", "reason", "arguments", "result", "failure"},
        )

    return json.loads(
        json.dumps(
            {
                "result": result,
                "requests": [
                    {
                        "label": record.label,
                        "status": record.status,
                        "state": record.state,
                        "questions": record.questions,
                        # the model reads questions, options and state in this order
                        "question_order": list(record.questions),
                        "option_order": {
                            key: list(question["options"])
                            for key, question in record.questions.items()
                            if "options" in question
                        },
                        "state_order": list(record.state)
                        if isinstance(record.state, dict)
                        else None,
                        "presentation": {
                            key: value.model_dump(mode="json")
                            for key, value in record.presentation.items()
                        },
                        "outcomes": outcomes(record.outcomes),
                        "actions": [action(entry) for entry in record.actions],
                        "policy_failure": record.policy_failure
                        and record.policy_failure.code,
                    }
                    for record in service.log.records.values()
                ],
                "invocations": [
                    {
                        "status": invocation.status,
                        "outcomes": outcomes(invocation.outcomes),
                        "actions": [action(entry) for entry in invocation.actions],
                    }
                    for invocation in service.log.invocations.values()
                ],
            },
            default=str,
        )
    )


@contextmanager
def golden_lock():
    deadline = time.monotonic() + 30
    while True:
        try:
            fd = os.open(LOCK, os.O_CREAT | os.O_EXCL)
            break
        except FileExistsError:
            if time.monotonic() > deadline:
                raise TimeoutError(f"Remove the stale lock file {LOCK}") from None
            time.sleep(0.05)
    try:
        yield
    finally:
        os.close(fd)
        LOCK.unlink()


def read_golden():
    return json.loads(GOLDEN.read_text()) if GOLDEN.exists() else {}


def write_golden(golden):
    GOLDEN.write_text(json.dumps(golden, indent=1, sort_keys=True) + "\n")


def check(name, service, result, update, uid):
    assert {i.template_uid for i in service.log.invocations.values()} == {uid}
    observed = trace(service, result)
    if update:
        with golden_lock():
            write_golden({**read_golden(), name: observed})
        return
    golden = read_golden()
    assert name in golden, (
        f"No golden case recorded for {name}. Run with --update-baselines."
    )
    assert observed == golden[name], (
        f"Decision request does not match the golden case {name}. "
        "Run with --update-baselines to update."
    )


@pytest.mark.parametrize(
    "name,uid,candidates,variables,answers",
    GATE_CASES,
    ids=[case[0] for case in GATE_CASES],
)
async def test_gate_template_matches_golden(
    gate_case, update_baselines, name, uid, candidates, variables, answers
):
    gate_case.provider.answers = answers

    async def fallback(keys):
        return {key: "fallback" for key in keys}

    result = await decision_gate(
        uid,
        enabled=True,
        candidates=candidates,
        variables=lambda: variables,
        fallback=fallback,
    )
    check(name, gate_case.service, result, update_baselines, uid)


MIXED_PROSE = (
    'She whispered "nobody" and scanned the empty platform once more. '
    "A shiver ran down her spine."
)

EDITOR_CASES = [
    ("editor-revision", "rewrite", 1, None, None, None),
    ("editor-revision-unslop", "unslop", 1, None, None, None),
    ("editor-below-thresholds", "rewrite", 1, {}, None, None),
    (
        "editor-below-minimum",
        "rewrite",
        2,
        {"s1_repetition": 0.93, "s1_style": 0.91},
        None,
        None,
    ),
    (
        "editor-at-threshold",
        "rewrite",
        1,
        {"s2_style": 0.8, "s1_repetition": 0.79},
        None,
        None,
    ),
    ("editor-nothing-in-scope", "rewrite", 1, None, "dialogue", None),
    ("editor-prose-scope", "rewrite", 1, {"s1_filler": 0.9}, "prose", None),
    (
        "editor-prose-scope-mixed",
        "rewrite",
        1,
        {"s1_filler": 0.9},
        "prose",
        MIXED_PROSE,
    ),
]


@pytest.mark.parametrize(
    "name,method,minimum,probabilities,scope,message",
    EDITOR_CASES,
    ids=[case[0] for case in EDITOR_CASES],
)
async def test_editor_template_matches_golden(
    editor_case,  # noqa: F811
    update_baselines,
    name,
    method,
    minimum,
    probabilities,
    scope,
    message,
):
    c = editor_case
    if message is not None:
        c.current.message = message
    c.editor.actions["revision"].config["revision_method"].value = method
    c.editor.actions["revision"].config["min_issues"].value = minimum
    if probabilities is not None:
        c.provider.probabilities = probabilities
    if scope:
        c.scene.test_writing_style.decision_checks = [scoped_check(scope)]
    result, _ = await revise(c)
    check(name, c.service, result, update_baselines, EDITOR_UID)


def referenced_template_names():
    env = jinja2.Environment(extensions=[CaptureContextExtension])
    return {
        name
        for path in TEMPLATES.glob("*/*.jinja2")
        for name in meta.find_referenced_templates(env.parse(path.read_text()))
        if name
    }


def test_helper_templates_are_included_by_other_templates():
    referenced = referenced_template_names()
    unused = sorted(
        helper
        for helper in HELPER_TEMPLATES
        if not (TEMPLATES / helper).exists() or Path(helper).name not in referenced
    )
    assert not unused, (
        f"HELPER_TEMPLATES lists templates that no other template includes or "
        f"imports: {unused}. Remove them, or give them a golden case if they "
        "render as policies."
    )


def test_every_policy_template_has_a_golden_case():
    policies = {
        f"{path.parent.name}.{path.stem}"
        for path in TEMPLATES.glob("*/decision-*.jinja2")
        if path.relative_to(TEMPLATES).as_posix() not in HELPER_TEMPLATES
    }
    covered = {case[1] for case in GATE_CASES} | {EDITOR_UID}
    missing = sorted(policies - covered)
    assert not missing, (
        f"Decision policy templates without a golden case: {missing}. Add a case "
        "to GATE_CASES or EDITOR_CASES and run with --update-baselines. A "
        "template that only other templates include or import belongs in "
        "HELPER_TEMPLATES."
    )


def test_golden_file_has_no_orphan_cases(update_baselines):
    names = {case[0] for case in [*GATE_CASES, *EDITOR_CASES]}
    with golden_lock():
        golden = read_golden()
        orphans = sorted(set(golden) - names)
        if update_baselines and orphans:
            write_golden({k: v for k, v in golden.items() if k in names})
            return
    assert not orphans, (
        f"Golden cases without a test case: {orphans}. "
        "Run with --update-baselines to remove them."
    )
