import json
import os
from pathlib import Path

import pytest

from talemate.decisions.gate import decision_gate

from test_editor_decision_checks import editor_case, revise, scoped_check  # noqa: F401

GOLDEN = Path(__file__).parents[1] / "data/decisions/template-golden.json"
RECORD = os.environ.get("TALEMATE_RECORD_DECISION_GOLDEN") == "1"


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
    options = "portraits" if kind == "portrait" else "backgrounds"

    def state(current):
        base = {"content": "Dawn breaks over the harbour."}
        if kind == "portrait":
            base["character"] = "Mara"
        return {**base, current_key: current, options: ASSETS}

    def case(name, current, fits, selected, confidence):
        return (
            f"{slot}-{name}",
            uid,
            {slot: list(ASSETS)},
            {"state": state(current)},
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
        {"text": "The captain waved.", "characters": CHARACTERS},
        {key: noul(p) for key, p in probabilities.items()},
    )


GATE_CASES = [
    *[
        (
            f"query-{p}",
            "world_state.decision-query",
            {"query": [True, False]},
            {"query": "Is the door open?", "text": "The door is open."},
            {"query": noul(p)},
        )
        for p in (0.95, 0.9, 0.05, 0.1, 0.5)
    ],
    (
        "pins",
        "world_state.decision-pin-conditions",
        {key: [True, False] for key in PINS},
        {"pins": PINS, "history": ["The door opens.", "Nobody is asleep."]},
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


def check(name, observed):
    golden = json.loads(GOLDEN.read_text()) if GOLDEN.exists() else {}
    if RECORD:
        golden[name] = observed
        GOLDEN.write_text(json.dumps(golden, indent=1, sort_keys=True) + "\n")
        return
    assert observed == golden[name]


@pytest.mark.parametrize(
    "name,uid,candidates,variables,answers",
    GATE_CASES,
    ids=[case[0] for case in GATE_CASES],
)
async def test_gate_template_matches_golden(
    gate_case, name, uid, candidates, variables, answers
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
    check(name, trace(gate_case.service, result))


EDITOR_CASES = [
    ("editor-revision", "rewrite", 1, None, None),
    ("editor-revision-unslop", "unslop", 1, None, None),
    ("editor-below-thresholds", "rewrite", 1, {}, None),
    (
        "editor-below-minimum",
        "rewrite",
        2,
        {"s1_repetition": 0.93, "s1_style": 0.91},
        None,
    ),
    (
        "editor-at-threshold",
        "rewrite",
        1,
        {"s2_style": 0.8, "s1_repetition": 0.79},
        None,
    ),
    ("editor-nothing-in-scope", "rewrite", 1, None, "dialogue"),
    ("editor-prose-scope", "rewrite", 1, {"s1_filler": 0.9}, "prose"),
]


@pytest.mark.parametrize(
    "name,method,minimum,probabilities,scope",
    EDITOR_CASES,
    ids=[case[0] for case in EDITOR_CASES],
)
async def test_editor_template_matches_golden(
    editor_case,  # noqa: F811
    name,
    method,
    minimum,
    probabilities,
    scope,
):
    c = editor_case
    c.editor.actions["revision"].config["revision_method"].value = method
    c.editor.actions["revision"].config["min_issues"].value = minimum
    if probabilities is not None:
        c.provider.probabilities = probabilities
    if scope:
        c.scene.test_writing_style.decision_checks = [scoped_check(scope)]
    result, _ = await revise(c)
    check(name, trace(c.service, result))
