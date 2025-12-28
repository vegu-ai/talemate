"""
Utility functions for agent operations.
"""

from talemate.emit import emit
from talemate.exceptions import GenerationCancelled

__all__ = [
    "EMPTY_RESPONSE_LIMIT",
    "EMPTY_RESPONSE_TROUBLESHOOTING_MESSAGE",
    "handle_empty_response_limit",
]

# Constants
EMPTY_RESPONSE_LIMIT = 2
EMPTY_RESPONSE_TROUBLESHOOTING_MESSAGE = (
    "The LLM client connected to the `{agent_name}` agent returned empty response(s).\n\n"
    "- Check if a reasoning model is loaded. If yes, ensure reasoning is enabled in client settings on the Talemate instance.\n"
    "- If reasoning is already enabled, try increasing the reasoning budget.\n"
    "- If using a non-reasoning model, the issue may be with the model configuration or service connection.\n"
    "- If you're still stuck, reach out in Discord for assistance."
)


def handle_empty_response_limit(agent_name: str, empty_result_count: int) -> None:
    """
    Emit troubleshooting message and raise GenerationCancelled when empty response limit is reached.

    Args:
        agent_name: The agent that encountered empty responses
        empty_result_count: The number of empty responses received
    """
    emit(
        "system",
        message=EMPTY_RESPONSE_TROUBLESHOOTING_MESSAGE.format(agent_name=agent_name),
        meta={
            "as_markdown": True,
            "color": "warning",
            "icon": "mdi-robot-dead",
            "title": "Empty Response(s)",
        },
    )
    raise GenerationCancelled(f"Received {empty_result_count} empty responses from AI")
