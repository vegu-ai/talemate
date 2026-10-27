from talemate.game.focal.schema import CallRejected, CallOutcome

__all__ = [
    "ActionFailed",
    "ActionRejected",
    "UnknownAction",
]


class ActionFailed(RuntimeError):
    """Raised when an action fails during execution.

    The message is communicated back to the director as an error result.
    """

    focal_reraise: bool = True

    def __init__(self, message: str):
        super().__init__(message)


class UnknownAction(ValueError):
    """Raised when an unknown action is requested."""

    def __init__(self, action_name: str):
        self.action_name = action_name
        super().__init__(f"Unknown action: {action_name}")


class ActionRejected(CallRejected):
    """Raised when a user rejects an action."""

    focal_reraise: bool = True

    def __init__(
        self,
        action_name: str,
        action_description: str,
        *,
        reason: CallOutcome = "reject",
        instructions: str = "",
    ):
        self.action_name = action_name
        self.action_description = action_description
        super().__init__(
            f"Action {reason}: {action_name} -> {action_description}",
            reason,
            instructions,
        )
