from .base import Agent
from .registry import register


@register
class ContextAgent(Agent):
    """
    Agent that helps retrieve context for the continuation
    of dialogue.
    """

    agent_type = "context"

    def __init__(self, client, **kwargs):
        self.client = client

    def determine_questions(self, scene_text):
        prompt = [
            "You are tasked to continue the following dialogue in a roleplaying session, but before you can do so you can ask three questions for extra context."
            "",
            "What are the questions you would ask?",
            "",
            "Known context and dialogue:" "",
            scene_text,
            "",
            "Questions:",
            "",
        ]

        prompt = "\n".join(prompt)

        questions = self.client.send_prompt(prompt, kind="question")

        questions = self.clean_result(questions)

        return questions.split("\n")

    def get_answer(self, question, context):
        prompt = [
            "Read the context and answer the question:",
            "",
            "Context:",
            "",
            context,
            "",
            f"Question: {question}",
            "Answer:",
        ]

        prompt = "\n".join(prompt)

        answer = self.client.send_prompt(prompt, kind="answer")
        answer = self.clean_result(answer)
        return answer
