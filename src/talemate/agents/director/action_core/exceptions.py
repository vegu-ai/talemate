__all__ = [
    "ActionRejected",
    "UnknownAction",
]


class UnknownAction(ValueError):
    """Raised when an unknown action is requested."""

    def __init__(self, action_name: str):
        self.action_name = action_name
        super().__init__(f"Unknown action: {action_name}")


class ActionRejected(IOError):
    """Raised when a user rejects an action."""

    focal_reraise: bool = True

    def __init__(self, action_name: str, action_description: str):
        self.action_name = action_name
        self.action_description = action_description
        super().__init__(f"User REJECTED action: {action_name} -> {action_description}")
