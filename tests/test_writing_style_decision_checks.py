import copy

import pytest
from pydantic import ValidationError

from talemate.world_state.templates.base import Group
from talemate.world_state.templates.content import WritingStyle
from talemate.world_state.templates.decision_checks import (
    default_writing_style_decision_checks,
)


def test_missing_and_empty_checks_remain_empty():
    assert WritingStyle(name="Existing style").decision_checks == []
    assert WritingStyle(name="Empty style", decision_checks=[]).decision_checks == []


def test_stored_check_without_scope_loads_as_all():
    stored = default_writing_style_decision_checks()[0].model_dump(mode="json")
    del stored["scope"]
    style = WritingStyle(name="Stored", decision_checks=[stored])
    assert style.decision_checks[0].scope == "all"


@pytest.mark.parametrize("scope", ["all", "dialogue", "prose"])
def test_scope_roundtrips(scope):
    stored = default_writing_style_decision_checks()[0].model_dump(mode="json")
    stored["scope"] = scope
    style = WritingStyle(name="Stored", decision_checks=[stored])
    assert style.model_dump(mode="json")["decision_checks"][0]["scope"] == scope


def test_default_checks_are_independent_and_preserve_tuned_wording():
    checks = default_writing_style_decision_checks()
    assert [check.name for check in checks] == [
        "Repeated beats and description reuse",
        "Writing style and unwanted prose",
        "Repeated dialogue and behavioural tics",
        "Overdescription and filler prose",
    ]
    assert [check.threshold for check in checks] == [0.8, 0.8, 0.8, 0.5]
    assert [check.scope for check in checks] == ["all", "all", "all", "prose"]
    assert [len(check.questions) for check in checks] == [2, 1, 2, 1]
    assert [q.id for q in checks[2].questions + checks[3].questions] == [
        "dialogue_tic",
        "mannerism_tic",
        "overdescription",
    ]
    beat, reuse = checks[0].questions
    assert beat.id == "repetition"
    assert "Judge meaning, not shared words." in beat.question
    assert reuse.id == "description_reuse"
    assert "even if this describes a new occurrence" in reuse.true_criteria
    assert "Preserve the event and factual content" in reuse.instructions
    checks[0].threshold = 0.9
    checks[0].questions[0].question = "Changed"
    assert default_writing_style_decision_checks()[0].threshold == 0.8
    assert default_writing_style_decision_checks()[0].questions[0].question != "Changed"


def test_template_group_roundtrip_preserves_check_edits_and_explicit_empty(tmp_path):
    style = WritingStyle(
        name="Plain",
        template_type="writing_style",
        decision_checks=default_writing_style_decision_checks(),
    )
    style.decision_checks[0].threshold = 0.93
    style.decision_checks[0].questions[
        1
    ].instructions = "Keep the action, replace the image."
    style.decision_checks[1].active = False
    empty = WritingStyle(
        name="Empty", template_type="writing_style", decision_checks=[]
    )
    group = Group(
        name="Styles",
        author="Test",
        description="",
        templates={style.uid: style, empty.uid: empty},
    )
    group.save(str(tmp_path))
    loaded = Group.load(group.path)
    assert loaded.templates[style.uid].decision_checks == style.decision_checks
    assert loaded.templates[empty.uid].decision_checks == []
    exported = loaded.model_dump(mode="json")
    assert (
        Group.model_validate(exported).templates[style.uid].decision_checks
        == style.decision_checks
    )


@pytest.mark.parametrize("threshold", [-0.1, 1.1, float("nan"), float("inf")])
def test_invalid_threshold_is_rejected(threshold):
    checks = [check.model_dump() for check in default_writing_style_decision_checks()]
    checks[0]["threshold"] = threshold
    with pytest.raises(ValidationError):
        WritingStyle(name="Invalid", decision_checks=checks)


@pytest.mark.parametrize(
    "invalid",
    [
        "duplicate",
        "bad_id",
        "empty_question",
        "empty_instructions",
        "empty_group",
        "route",
    ],
)
def test_invalid_questions_are_rejected(invalid):
    checks = [check.model_dump() for check in default_writing_style_decision_checks()]
    question = checks[0]["questions"][0]
    if invalid == "duplicate":
        checks[1]["questions"].append(copy.deepcopy(question))
    elif invalid == "bad_id":
        question["id"] = "spaces are invalid"
    elif invalid == "empty_question":
        question["question"] = ""
    elif invalid == "empty_instructions":
        question["instructions"] = ""
    elif invalid == "empty_group":
        checks[0]["questions"] = []
    else:
        question["kind"] = "arbitrary_agent_action"
    with pytest.raises(ValidationError):
        WritingStyle(name="Invalid", decision_checks=checks)


async def test_template_catalog_supplies_default_checks_without_changing_styles():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from talemate.server.world_state_manager import templates_message
    from talemate.world_state.templates.base import Collection

    style = WritingStyle(name="Existing", template_type="writing_style")
    group = Group(
        name="Styles", author="Test", description="", templates={style.uid: style}
    )
    collection = Collection(groups=[group])
    manager = SimpleNamespace(
        template_collection=collection,
        get_templates=AsyncMock(return_value=collection.typed()),
    )
    message = await templates_message(manager)
    defaults = message["data"]["defaults"]["writing_style"]["decision_checks"]
    assert defaults == [
        check.model_dump(mode="json")
        for check in default_writing_style_decision_checks()
    ]
    assert (
        message["data"]["by_type"]["writing_style"][f"{group.uid}__{style.uid}"][
            "decision_checks"
        ]
        == []
    )


@pytest.mark.parametrize("field", ["question", "instructions"])
def test_whitespace_only_question_content_is_rejected(field):
    checks = [check.model_dump() for check in default_writing_style_decision_checks()]
    checks[0]["questions"][0][field] = " \n\t"
    with pytest.raises(ValidationError):
        WritingStyle(name="Invalid", decision_checks=checks)


@pytest.mark.parametrize(
    "invalid",
    [
        "duplicate",
        "bad_id",
        "kind",
        "missing_id",
        "null_true_criteria",
        "null_false_criteria",
        "authored_id_collision",
        "threshold_high",
        "threshold_low",
        "threshold_nan",
        "empty_question",
        "malformed_list",
        "scope",
    ],
)
def test_disk_load_repairs_checks_and_group_save_preserves_style(tmp_path, invalid):
    import yaml

    style = WritingStyle(
        name="Shared style",
        template_type="writing_style",
        description="Keep this description.",
        instructions="Keep concrete details.",
        phrases=[{"phrase": "old phrase", "instructions": "Use a fresh image."}],
        decision_checks=default_writing_style_decision_checks(),
    )
    sibling = WritingStyle(name="Another style", template_type="writing_style")
    group = Group(
        name="Shared",
        author="Test",
        description="",
        templates={style.uid: style, sibling.uid: sibling},
    )
    data = group.model_dump(mode="json")
    checks = data["templates"][style.uid]["decision_checks"]
    if invalid == "duplicate":
        checks[1]["questions"][0]["id"] = checks[0]["questions"][0]["id"]
    elif invalid == "bad_id":
        checks[0]["questions"][0]["id"] = "bad id"
    elif invalid == "kind":
        checks[0]["questions"][0]["kind"] = "future_kind"
    elif invalid == "missing_id":
        del checks[0]["questions"][0]["id"]
    elif invalid.startswith("null_"):
        checks[0]["questions"][0][invalid.removeprefix("null_")] = None
    elif invalid == "authored_id_collision":
        checks[0]["questions"][0]["id"] = "bad id"
        checks[0]["questions"][1]["id"] = "also bad"
        checks[1]["questions"][0]["id"] = "question"
    elif invalid.startswith("threshold"):
        checks[0]["threshold"] = {
            "threshold_high": 1.5,
            "threshold_low": -0.5,
            "threshold_nan": float("nan"),
        }[invalid]
    elif invalid == "empty_question":
        checks[0]["questions"][0]["question"] = "   "
    elif invalid == "scope":
        checks[0]["scope"] = "speech"
    else:
        data["templates"][style.uid]["decision_checks"] = "not a list"
    with pytest.raises(ValidationError):
        WritingStyle.model_validate(data["templates"][style.uid])
    path = tmp_path / "shared.yaml"
    path.write_text(yaml.safe_dump(data))
    loaded = Group.load(str(path))
    repaired = loaded.templates[style.uid]
    assert repaired.instructions == style.instructions
    assert repaired.description == style.description
    assert repaired.phrases == style.phrases
    assert len(repaired.decision_checks) == (
        0 if invalid == "malformed_list" else 3 if invalid == "empty_question" else 4
    )
    questions = [q for c in repaired.decision_checks for q in c.questions]
    assert len({q.id for q in questions}) == len(questions)
    if invalid == "kind":
        assert questions[0].kind == "style"
    if invalid == "missing_id":
        assert questions[0].id == "question"
    if invalid.startswith("null_"):
        assert getattr(questions[0], invalid.removeprefix("null_")) == ""
    if invalid == "authored_id_collision":
        assert [q.id for q in questions][:3] == ["question_2", "question_3", "question"]
    if invalid.startswith("threshold"):
        assert (
            repaired.decision_checks[0].threshold
            == {"threshold_high": 1.0, "threshold_low": 0.0, "threshold_nan": 0.8}[
                invalid
            ]
        )
    if invalid == "scope":
        assert repaired.decision_checks[0].scope == "all"
    loaded.update_template(sibling.model_copy(update={"description": "Edited sibling"}))
    assert Group.load(str(path)).templates[style.uid] == repaired
