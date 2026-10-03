import json

from _knowledge_step_helpers import push_and_step

from talemate.scene_message import NarratorMessage


def analysis(cite_knowledge=True, cite_passages=True):
    """A perception answer in which each view cites what it is offered."""

    async def answer(*args, **kwargs):
        context = kwargs["vars"]["context"]
        passage = context["passage"]["provenance"]["message_id"]
        views = [
            {
                "audience": [entry["name"]],
                "status": "ready",
                "text": f"{entry['name']} notices passage {passage}.",
                "knowledge_ids": [item["id"] for item in entry["established_knowledge"]]
                if cite_knowledge
                else [],
                "passage_ids": [
                    item["id"] for item in context["prior_physical_context"]
                ]
                if cite_passages
                else [],
            }
            for entry in context["cast"]
        ]
        text = json.dumps({"views": views})
        return text, {"response": text}

    return answer


async def story(scene, count=5):
    messages = [
        NarratorMessage(message=f"Line {index}.", source="narrate_scene")
        for index in range(count)
    ]
    for message in messages:
        await push_and_step(scene, message)
    return messages


def replace_view(message, name, **update):
    knowledge = message.knowledge
    views = tuple(
        view.model_copy(update=update) if name in view.audience else view
        for view in knowledge.views
    )
    object.__setattr__(
        message, "knowledge", knowledge.model_copy(update={"views": views})
    )
