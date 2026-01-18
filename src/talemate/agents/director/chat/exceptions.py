__all__ = [
    "InvalidDirectorChat",
]


class InvalidDirectorChat(ValueError):
    """Raised when a chat ID is invalid or not found."""

    def __init__(self, chat_id: str):
        self.chat_id = chat_id
        super().__init__(f"Invalid chat: {chat_id}")
