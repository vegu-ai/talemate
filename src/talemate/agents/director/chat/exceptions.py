__all__ = [
    "DirectorChatActionRejected",
    "UnknownDirectorChatAction",
    "InvalidDirectorChat",
]


class InvalidDirectorChat(ValueError):
    def __init__(self, chat_id: str):
        self.chat_id = chat_id
        super().__init__(f"Invalid chat: {chat_id}")


class UnknownDirectorChatAction(ValueError):
    def __init__(self, action_name: str):
        self.action_name = action_name
        super().__init__(f"Unknown action: {action_name}")


class DirectorChatActionRejected(IOError):
    focal_reraise: bool = True

    def __init__(self, action_name: str, action_description: str):
        self.action_name = action_name
        self.action_description = action_description
        super().__init__(f"User REJECTED action: {action_name} -> {action_description}")
