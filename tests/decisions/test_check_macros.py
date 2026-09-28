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
