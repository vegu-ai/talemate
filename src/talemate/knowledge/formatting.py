from talemate.scene_message import (
    CharacterMessage,
    ContextInvestigationMessage,
    ReinforcementMessage,
    SceneMessage,
)


def perception_speaker(message: SceneMessage) -> str | None:
    return message.character_name if isinstance(message, CharacterMessage) else None


def perception_body(message: SceneMessage) -> str:
    text = message.perception_text
    if isinstance(message, CharacterMessage) and ":" in message.message:
        prefix = f"{message.character_name}:"
        if text.startswith(prefix):
            return text[len(prefix) :].lstrip()
    elif isinstance(message, (ReinforcementMessage, ContextInvestigationMessage)):
        return text.removeprefix(message.perception_prefix)
    return text


def passage_metadata(message: SceneMessage) -> dict:
    return {
        "kind": message.typ,
        "speaker": message.character_name
        if isinstance(message, CharacterMessage)
        else None,
        "sub_type": message.sub_type
        if isinstance(message, ContextInvestigationMessage)
        else None,
        "subject_character": message.source_arguments.get("character")
        if isinstance(message, (ContextInvestigationMessage, ReinforcementMessage))
        else None,
    }


def format_message_view(message, text, conversation_format):
    if isinstance(message, (ReinforcementMessage, ContextInvestigationMessage)):
        # Restore only the note framing and subject, never an excluded question.
        text = message.perception_prefix + text
        return SceneMessage.as_format(
            message.model_copy(update={"message": text}), conversation_format
        )
    if isinstance(message, CharacterMessage) and ":" in message.message:
        text = f"{message.character_name}: {text}"
    projected = message.model_copy(update={"message": text})
    if isinstance(message, CharacterMessage) and ":" not in message.message:
        return SceneMessage.as_format(projected, conversation_format)
    return projected.as_format(conversation_format)
