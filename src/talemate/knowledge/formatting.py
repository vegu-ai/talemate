from talemate.scene_message import CharacterMessage, SceneMessage


def format_message_view(message, text, conversation_format):
    if message.typ in ("reinforcement", "context_investigation"):
        # The replacement already includes everything the audience may know of
        # the heading/question. Never append the reader's original heading.
        return SceneMessage.as_format(
            message.model_copy(update={"message": text}), conversation_format
        )
    if isinstance(message, CharacterMessage) and ":" in message.message:
        text = CharacterMessage.with_name_prefix(message.character_name, text)
    projected = message.model_copy(update={"message": text})
    if isinstance(message, CharacterMessage) and ":" not in message.message:
        return SceneMessage.as_format(projected, conversation_format)
    return projected.as_format(conversation_format)
