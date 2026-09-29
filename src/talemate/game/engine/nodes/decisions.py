import uuid

from talemate.decisions import DecisionHandle, decision_service
from talemate.decisions.slot import decision_model_status

from .core import UNRESOLVED, GraphState, InputValueError, Node, PropertyField
from .registry import register

__all__ = [
    "AskDecisionModel",
    "DecideYesNo",
    "DecisionModelStatus",
]

TEMPLATE_UID = "node_editor.decision"
QUESTION_ID = "question"


def _subject(value) -> str | dict | list:
    if value is None:
        return ""
    if isinstance(value, (str, dict, list)):
        return value
    return str(value)


async def _evaluate(label: str, state, question: dict):
    return await decision_service.evaluate(
        label,
        state=state,
        questions={QUESTION_ID: question},
        invocation_id=str(uuid.uuid4()),
        template_uid=TEMPLATE_UID,
    )


@register("decisions/AskDecisionModel")
class AskDecisionModel(Node):
    """
    Ask the decision model one question about a subject and read the answer as
    probabilities. Nothing is sent while the decision model is off; the node
    then outputs available=False and the reason in failure_code.

    Question types:

    - noul: yes/no; the answer is p_true
    - choice: pick one of `options` (dict of option id to description); the answer is selected
    - score: rate on `rubric` (list of level descriptions, lowest first); the answer is value

    Inputs:

    - state: graph state; the node sends the request only when a value
      reaches it
    - subject: text or data the question is about (optional)
    - instructions: the question
    - true_criteria: when the answer is yes (noul, optional)
    - false_criteria: when the answer is no (noul, optional)
    - options: choice options (choice)
    - rubric: score levels (score)

    Properties:

    - question_type: noul, choice or score
    - label: name of the request in the Decision Log

    Outputs:

    - state: graph state
    - available: True when the decision model answered
    - failure_code: why there is no answer (disabled, unavailable, timeout, oversize, invalid_request ...), or None
    - request_id: the Decision Log request id
    - p_true: probability of yes (noul)
    - selected: the most probable option (choice)
    - value: the expected score (score)
    - probabilities: probability per option (choice) or per rubric level (score)
    - confidence: the model's confidence (choice, score)
    - answer: the full answer as a dict
    """

    class Fields:
        question_type = PropertyField(
            name="question_type",
            description="What kind of answer the question has",
            type="str",
            default="noul",
            choices=["noul", "choice", "score"],
        )
        label = PropertyField(
            name="label",
            description="Name of the request in the Decision Log",
            type="str",
            default="Node graph question",
        )
        instructions = PropertyField(
            name="instructions",
            description="The question",
            type="text",
            default="",
        )
        true_criteria = PropertyField(
            name="true_criteria",
            description="When the answer is yes (noul)",
            type="text",
            default="",
        )
        false_criteria = PropertyField(
            name="false_criteria",
            description="When the answer is no (noul)",
            type="text",
            default="",
        )
        options = PropertyField(
            name="options",
            description="Option id to description (choice)",
            type="dict",
            default={},
        )
        rubric = PropertyField(
            name="rubric",
            description="Level descriptions, lowest first (score)",
            type="list",
            default=[],
        )

    def __init__(self, title="Ask Decision Model", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("subject", socket_type="str,dict,list", optional=True)
        self.add_input("instructions", socket_type="str", optional=True)
        self.add_input("true_criteria", socket_type="str", optional=True)
        self.add_input("false_criteria", socket_type="str", optional=True)
        self.add_input("options", socket_type="dict", optional=True)
        self.add_input("rubric", socket_type="list", optional=True)

        self.set_property("question_type", "noul")
        self.set_property("label", "Node graph question")
        self.set_property("instructions", "")
        self.set_property("true_criteria", "")
        self.set_property("false_criteria", "")
        self.set_property("options", {})
        self.set_property("rubric", [])

        self.add_output("state")
        self.add_output("available", socket_type="bool")
        self.add_output("failure_code", socket_type="str")
        self.add_output("request_id", socket_type="str")
        self.add_output("p_true", socket_type="float")
        self.add_output("selected", socket_type="str")
        self.add_output("value", socket_type="float")
        self.add_output("probabilities", socket_type="dict,list")
        self.add_output("confidence", socket_type="float")
        self.add_output("answer", socket_type="dict")

    def build_question(self) -> dict:
        question_type = self.get_property("question_type")
        instructions = self.normalized_input_value("instructions")
        if not instructions or not str(instructions).strip():
            raise InputValueError(self, "instructions", "The question is empty.")
        question = {"type": question_type, "instructions": str(instructions)}
        if question_type == "noul":
            for name in ("true_criteria", "false_criteria"):
                value = self.normalized_input_value(name)
                if value and str(value).strip():
                    question[name] = str(value)
        elif question_type == "choice":
            options = self.normalized_input_value("options") or {}
            if len(options) < 2:
                raise InputValueError(self, "options", "A choice needs two options.")
            question["options"] = {str(k): str(v) for k, v in options.items()}
        elif question_type == "score":
            rubric = self.normalized_input_value("rubric") or []
            if len(rubric) < 2:
                raise InputValueError(self, "rubric", "A score needs two levels.")
            question["rubric"] = [str(level) for level in rubric]
        else:
            raise InputValueError(
                self,
                "question_type",
                f"`{question_type}` is not noul, choice or score.",
            )
        return question

    async def run(self, state: GraphState):
        question = self.build_question()
        result = await _evaluate(
            self.get_property("label") or "Node graph question",
            _subject(self.normalized_input_value("subject")),
            question,
        )
        outputs = {
            "state": self.get_input_value("state"),
            "available": False,
            "failure_code": None,
            "request_id": result.request_id,
            "p_true": None,
            "selected": None,
            "value": None,
            "probabilities": None,
            "confidence": None,
            "answer": None,
        }
        if isinstance(result, DecisionHandle):
            answer = result.answers[QUESTION_ID]
            outputs.update(
                {
                    "available": True,
                    "p_true": getattr(answer, "p_true", None),
                    "selected": getattr(answer, "selected", None),
                    "value": getattr(answer, "value", None),
                    "probabilities": getattr(answer, "probabilities", None),
                    "confidence": getattr(answer, "confidence", None),
                    "answer": answer.model_dump(),
                }
            )
        else:
            outputs["failure_code"] = result.failure.code.value
        self.set_output_values(outputs)


@register("decisions/DecideYesNo")
class DecideYesNo(Node):
    """
    Ask the decision model a yes/no question and route on the answer.
    `yes` is active when p_true reaches the threshold, `no` when 1 - p_true
    reaches it, and `uncertain` otherwise, including when the decision model is
    off or fails. Wire `uncertain` to a fallback, for example an LLM query.

    Inputs:

    - state: graph state; the node sends the request only when a value
      reaches it
    - subject: text or data the question is about (optional)
    - instructions: the question
    - true_criteria: when the answer is yes (optional)
    - false_criteria: when the answer is no (optional)
    - threshold: minimum probability for yes or no

    Properties:

    - label: name of the request in the Decision Log

    Outputs:

    - state: graph state
    - yes: active when the answer is yes
    - no: active when the answer is no
    - uncertain: active when neither reaches the threshold or there is no answer
    - p_true: probability of yes, or None without an answer
    - failure_code: why there is no answer, or None
    """

    class Fields:
        label = PropertyField(
            name="label",
            description="Name of the request in the Decision Log",
            type="str",
            default="Node graph question",
        )
        instructions = PropertyField(
            name="instructions",
            description="The question",
            type="text",
            default="",
        )
        true_criteria = PropertyField(
            name="true_criteria",
            description="When the answer is yes",
            type="text",
            default="",
        )
        false_criteria = PropertyField(
            name="false_criteria",
            description="When the answer is no",
            type="text",
            default="",
        )
        threshold = PropertyField(
            name="threshold",
            description="Minimum probability for yes or no",
            type="number",
            default=0.9,
            min=0.5,
            max=1.0,
            step=0.01,
        )

    def __init__(self, title="Decide Yes/No", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("subject", socket_type="str,dict,list", optional=True)
        self.add_input("instructions", socket_type="str", optional=True)
        self.add_input("true_criteria", socket_type="str", optional=True)
        self.add_input("false_criteria", socket_type="str", optional=True)
        self.add_input("threshold", socket_type="int,float", optional=True)

        self.set_property("label", "Node graph question")
        self.set_property("instructions", "")
        self.set_property("true_criteria", "")
        self.set_property("false_criteria", "")
        self.set_property("threshold", 0.9)

        self.add_output("state")
        self.add_output("yes", socket_type="bool")
        self.add_output("no", socket_type="bool")
        self.add_output("uncertain", socket_type="bool")
        self.add_output("p_true", socket_type="float")
        self.add_output("failure_code", socket_type="str")

    async def run(self, state: GraphState):
        instructions = self.normalized_input_value("instructions")
        if not instructions or not str(instructions).strip():
            raise InputValueError(self, "instructions", "The question is empty.")
        threshold = float(self.require_number_input("threshold"))
        if not 0.5 <= threshold <= 1:
            raise InputValueError(
                self, "threshold", "The threshold must be between 0.5 and 1."
            )
        question = {"type": "noul", "instructions": str(instructions)}
        for name in ("true_criteria", "false_criteria"):
            value = self.normalized_input_value(name)
            if value and str(value).strip():
                question[name] = str(value)

        result = await _evaluate(
            self.get_property("label") or "Node graph question",
            _subject(self.normalized_input_value("subject")),
            question,
        )
        p_true = None
        failure_code = None
        route = "uncertain"
        if isinstance(result, DecisionHandle):
            p_true = result.answers[QUESTION_ID].p_true
            if p_true >= threshold:
                route = "yes"
            elif 1 - p_true >= threshold:
                route = "no"
        else:
            failure_code = result.failure.code.value

        for name in ("yes", "no", "uncertain"):
            self.get_output_socket(name).deactivated = name != route
        self.set_output_values(
            {
                "state": self.get_input_value("state"),
                "yes": True if route == "yes" else UNRESOLVED,
                "no": True if route == "no" else UNRESOLVED,
                "uncertain": True if route == "uncertain" else UNRESOLVED,
                "p_true": p_true,
                "failure_code": failure_code,
            }
        )


@register("decisions/DecisionModelStatus")
class DecisionModelStatus(Node):
    """
    Whether the decision model can answer questions now. Use it to skip
    building an expensive state when no answer can come.

    Outputs:

    - ready: True when the decision model is on and its setup is complete
    - enabled: True when the decision model is on
    - status: disabled, incomplete or ready
    - provider: the provider name, or None
    - model: the model id
    """

    def __init__(self, title="Decision Model Status", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_output("ready", socket_type="bool")
        self.add_output("enabled", socket_type="bool")
        self.add_output("status", socket_type="str")
        self.add_output("provider", socket_type="str")
        self.add_output("model", socket_type="str")

    async def run(self, state: GraphState):
        status = decision_model_status()
        provider = decision_service.provider
        self.set_output_values(
            {
                "ready": bool(
                    status.state == "ready" and provider is not None and provider.ready
                ),
                "enabled": status.enabled,
                "status": status.state,
                "provider": status.provider,
                "model": status.model,
            }
        )
