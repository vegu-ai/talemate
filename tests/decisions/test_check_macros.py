import pytest

from talemate.decisions.models import NoulAnswer
from talemate.world_state.templates.decision_checks import DecisionCheck


async def test_common_macros_build_and_filter_two_checks_for_two_passages(
    policy_factory,
):
    checks = [
        DecisionCheck(
            name="Repeated beat",
            threshold=0.8,
            questions=[
                {
                    "id": "repeat",
                    "question": "Does {passage_id} repeat a beat?",
                    "true_criteria": "Repeated in {passage_id}.",
                    "false_criteria": "New in {passage_id}.",
                    "kind": "repetition",
                    "instructions": "Remove the repeated beat.",
                }
            ],
        ),
        DecisionCheck(
            name="Concrete prose",
            threshold=0.6,
            questions=[
                {
                    "id": "abstract",
                    "question": "Is it too abstract?",
                    "true_criteria": "Only one criterion.",
                    "instructions": "Use a concrete detail.",
                }
            ],
        ),
    ]
    passages = [{"id": "s1", "text": "First."}, {"id": "s2", "text": "Second."}]
    probabilities = {
        "s1_repeat": 0.8,
        "s1_abstract": 0.7,
        "s2_repeat": 0.79,
        "s2_abstract": 0.59,
    }
    invocation = policy_factory.create(
        """
        {% import "decision-check-macros.jinja2" as checks %}
        {% set batch = namespace() %}
        {% set results = namespace() %}
        {% set _ = checks.build_questions(passages, decision_checks, batch) %}
        {% set _ = checks.collect_findings(answers, batch.evaluations, results) %}
        {{ decision_result({"questions": batch.questions, "presentation": batch.presentation,
            "evaluations": batch.evaluations, "findings": results.findings,
            "flagged": results.flagged, "flagged_questions": results.flagged_questions,
            "thresholds": results.thresholds}) }}
        """,
        uid="narrator.shared-checks",
        variables={
            "passages": passages,
            "decision_checks": checks,
            "answers": {
                key: NoulAnswer(type="noul", p_true=value)
                for key, value in probabilities.items()
            },
        },
        validate_result=lambda value: value,
    )

    result = await invocation.run()

    assert invocation.status == "completed"
    assert list(result["questions"]) == list(probabilities)
    for passage in passages:
        pid = passage["id"]
        assert result["questions"][f"{pid}_repeat"] == {
            "type": "noul",
            "instructions": f"Does {pid} repeat a beat?",
            "true_criteria": f"Repeated in {pid}.",
            "false_criteria": f"New in {pid}.",
        }
        assert result["questions"][f"{pid}_abstract"] == {
            "type": "noul",
            "instructions": f"Passage {pid}: Is it too abstract?",
            "true_criteria": None,
            "false_criteria": None,
        }
        assert result["presentation"][f"{pid}_repeat"] == {
            "group_id": "repeat",
            "label": "Repeated beat",
            "instructions": "Does shown below repeat a beat?",
            "passage_id": pid,
            "passage_text": passage["text"],
            "scope": "all",
            "threshold": 0.8,
        }
    assert result["thresholds"] == {
        "s1_repeat": 0.8,
        "s1_abstract": 0.6,
        "s2_repeat": 0.8,
        "s2_abstract": 0.6,
    }
    assert result["flagged"] == ["s1"]
    assert result["flagged_questions"] == ["s1_repeat", "s1_abstract"]
    assert result["findings"] == [
        {
            "passage_id": "s1",
            "text": "First.",
            "kind": "repetition",
            "instructions": "Remove the repeated beat.",
            "p_true": 0.8,
        },
        {
            "passage_id": "s1",
            "text": "First.",
            "kind": "style",
            "instructions": "Use a concrete detail.",
            "p_true": 0.7,
        },
    ]
    assert [item["id"] for item in result["evaluations"]] == list(probabilities)
    policy_factory.fallback.assert_not_awaited()


async def test_scoped_check_judges_its_part_and_skips_passages_without_it(
    policy_factory,
):
    checks = [
        DecisionCheck(
            name="Dialogue habits",
            scope="dialogue",
            questions=[
                {
                    "id": "habit",
                    "question": "Does {passage_id} repeat a catchphrase?",
                    "instructions": "Vary the line.",
                }
            ],
        ),
        DecisionCheck(
            name="Beats",
            questions=[
                {
                    "id": "beat",
                    "question": "Does {passage_id} repeat a beat?",
                    "instructions": "Remove the beat.",
                }
            ],
        ),
    ]
    passages = [
        {
            "id": "s1",
            "text": '"Curious weather." He smiled.',
            "dialogue": '"Curious weather."',
        },
        {"id": "s2", "text": "The lamp turned.", "dialogue": ""},
    ]
    invocation = policy_factory.create(
        """
        {% import "decision-check-macros.jinja2" as checks %}
        {% set batch = namespace() %}
        {% set results = namespace() %}
        {% set _ = checks.build_questions(passages, decision_checks, batch) %}
        {% set _ = checks.collect_findings(answers, batch.evaluations, results) %}
        {{ decision_result({"questions": batch.questions, "presentation": batch.presentation,
            "skipped": batch.skipped, "findings": results.findings}) }}
        """,
        uid="narrator.scoped-checks",
        variables={
            "passages": passages,
            "decision_checks": checks,
            "answers": {
                "s1_habit": NoulAnswer(type="noul", p_true=0.9),
                "s1_beat": NoulAnswer(type="noul", p_true=0.1),
                "s2_beat": NoulAnswer(type="noul", p_true=0.1),
            },
        },
        validate_result=lambda value: value,
    )

    result = await invocation.run()

    assert list(result["questions"]) == ["s1_habit", "s1_beat", "s2_beat"]
    assert result["questions"]["s1_habit"]["instructions"] == (
        "Judge only the dialogue of passage s1 (its `dialogue` text: the words inside"
        " double quotes); ignore its narration. Does s1 repeat a catchphrase?"
    )
    assert result["questions"]["s1_beat"]["instructions"] == "Does s1 repeat a beat?"
    assert result["presentation"]["s1_habit"]["passage_text"] == '"Curious weather."'
    assert result["presentation"]["s1_habit"]["scope"] == "dialogue"
    assert result["presentation"]["s1_beat"]["passage_text"] == passages[0]["text"]
    assert result["presentation"]["s1_beat"]["scope"] == "all"
    assert result["skipped"] == [
        {
            "group_id": "habit",
            "label": "Dialogue habits",
            "instructions": "Does shown below repeat a catchphrase?",
            "passage_id": "s2",
            "scope": "dialogue",
        }
    ]
    assert result["findings"] == [
        {
            "passage_id": "s1",
            "text": passages[0]["text"],
            "kind": "style",
            "instructions": "Vary the line. Change only the dialogue of this passage.",
            "p_true": 0.9,
        }
    ]


@pytest.mark.parametrize("marked", [True, False])
async def test_scoped_check_without_its_part(policy_factory, marked):
    checks = [
        DecisionCheck(
            name="Filler",
            scope="prose",
            questions=[
                {
                    "id": "filler",
                    "question": "Does {passage_id} pad the moment?",
                    "instructions": "Cut the padding.",
                }
            ],
        )
    ]
    passage = {"id": "s1", "text": '"Ornate dialogue.'}
    if marked:
        passage["no_reliable_split"] = True
    invocation = policy_factory.create(
        """
        {% import "decision-check-macros.jinja2" as checks %}
        {% set batch = namespace() %}
        {% set _ = checks.build_questions(passages, decision_checks, batch) %}
        {{ decision_result({"questions": batch.questions, "presentation": batch.presentation,
            "skipped": batch.skipped}) }}
        """,
        uid="narrator.scoped-without-part",
        variables={"passages": [passage], "decision_checks": checks},
        validate_result=lambda value: value,
    )

    result = await invocation.run()

    if marked:
        assert invocation.status == "completed"
        assert (
            result["questions"]["s1_filler"]["instructions"]
            == "Does s1 pad the moment?"
        )
        assert result["presentation"]["s1_filler"]["scope"] == "all"
        assert result["skipped"] == []
    else:
        # a missing part without the mark is a template error, not a silent All
        assert invocation.status == "fallback"
        policy_factory.fallback.assert_awaited_once()
