from talemate.agents.base import AgentAction, AgentActionConfig, set_processing
from talemate.decisions.budget import fit_text
from talemate.decisions.gate import decision_gate


class WorldStateQueriesMixin:
    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["queries"] = AgentAction(
            enabled=True,
            container=True,
            can_be_disabled=False,
            label="Yes/No Queries",
            icon="mdi-help-circle-outline",
            config={
                "decision_model": AgentActionConfig(
                    type="bool",
                    label="Use Decision Model",
                    description="Answer yes/no questions from Evaluate Query and scripts with the decision model first. Unclear or failed answers use the usual request.",
                    value=True,
                ),
            },
        )

    @set_processing
    async def answer_query_true_or_false(self, query: str, text: str) -> bool:
        scene = self.scene

        async def fallback(ids):
            response = await self.analyze_text_and_answer_question(
                query=f"{query} Answer with a yes or no.",
                text=text,
                response_length=10,
            )
            return {"query": response.lower().startswith("y")}

        answers = await decision_gate(
            "world_state.decision-query",
            enabled=self.resolve_config("queries", "decision_model"),
            candidates={"query": [True, False]},
            variables=lambda: {
                "query": query,
                "state": lambda budget: fit_text(text, budget),
            },
            fallback=fallback,
            is_current=lambda: self.scene is scene,
        )
        return answers["query"]
