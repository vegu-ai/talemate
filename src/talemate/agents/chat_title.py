"""
Shared chat title generation used by the director and help chats.
"""

from typing import TYPE_CHECKING

from talemate.prompts import Prompt
from talemate.prompts.response import AnchorExtractor, ResponseSpec

if TYPE_CHECKING:
    from talemate.client.base import ClientBase

__all__ = [
    "CHAT_TITLE_SPEC",
    "generate_chat_title",
]

CHAT_TITLE_SPEC = ResponseSpec(
    extractors={
        "title": AnchorExtractor(left="<TITLE>", right="</TITLE>"),
    },
    required=[],
)

MAX_TITLE_LENGTH = 60


async def generate_chat_title(
    client: "ClientBase", chat_excerpt: str, participant: str
) -> str | None:
    """
    Generate a short title for a chat, based on an excerpt of its messages.
    `participant` describes the non-user side of the conversation for the
    prompt (e.g. "an AI director").
    """
    response, extracted = await Prompt.request(
        "common.chat-title",
        client,
        "create_92",
        vars={"chat_excerpt": chat_excerpt, "participant": participant},
        response_spec=CHAT_TITLE_SPEC,
    )

    title = extracted.get("title") or (response.strip() if response else None)
    if not title:
        return None

    title = title.strip().strip("\"'")
    if len(title) > MAX_TITLE_LENGTH:
        title = title[: MAX_TITLE_LENGTH - 3] + "..."
    return title
