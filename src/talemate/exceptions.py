__all__ = [
    "TalemateError",
    "ControlFlowException",
    "TalemateInterrupt",
    "ExitScene",
    "RestartSceneLoop",
    "ResetScene",
    "GenerationCancelled",
    "GenerationProcessingError",
    "ReasoningResponseError",
    "RenderPromptError",
    "LLMAccuracyError",
    "SceneInactiveError",
    "UnknownDataSpec",
    "ActedAsCharacter",
    "AbortCommand",
    "AbortWaitForInput",
]


class TalemateError(Exception):
    pass


class ControlFlowException(Exception):
    """
    Control flow exceptions must propagate uncaught through signal receiver dispatch (`AsyncSignal.send`)

    `SceneInactiveError`, the client's `ClientDisabledError` and the node engine's `StopModule` are
    deliberately not members - receiver isolation applies to them.
    """

    pass


class TalemateInterrupt(ControlFlowException):
    """
    Exception to interrupt the game loop
    """

    pass


class ExitScene(TalemateInterrupt):
    """
    Exception to exit the scene
    """

    pass


class RestartSceneLoop(TalemateInterrupt):
    """
    Exception to switch the scene loop
    """

    pass


class ResetScene(TalemateInterrupt):
    """
    Exception to reset the scene
    """

    pass


class GenerationCancelled(TalemateInterrupt):
    """
    Interrupt current scene and return action to the user
    """

    def __init__(
        self,
        *args,
        by_user: bool = False,
        message_id: int | None = None,
        view_status: str | None = None,
        character: str | None = None,
    ):
        super().__init__(*args)
        self.by_user = by_user
        self.message_id = message_id
        self.view_status = view_status
        self.character = character
        self.reported = False


class GenerationProcessingError(TalemateError):
    """
    Exception to raise when there is an error processing a generation
    """

    pass


class ReasoningResponseError(GenerationProcessingError):
    """
    Exception to raise when there is an error processing a reasoning response
    """

    def __init__(self):
        super().__init__(
            "Reasoning response pattern not found in response - this means that either the pattern is wrong, the reasoning budget is too low or the model does not support reasoning."
        )


class RenderPromptError(TalemateError):
    """
    Exception to raise when there is an error rendering a prompt
    """

    pass


class LLMAccuracyError(TalemateError):
    """
    Exception to raise when the LLM response is not processable
    """

    def __init__(self, message: str, model_name: str = None):
        if model_name:
            message = f"{model_name} - {message}"

        super().__init__(message)
        self.model_name = model_name


class SceneInactiveError(TalemateError):
    """
    Exception to raise when the scene is not active
    """

    pass


class UnknownDataSpec(TalemateError):
    """
    Exception to raise when the data spec is unknown
    """

    pass


class ActedAsCharacter(ControlFlowException):
    """
    Raised when the user acts as another character
    than the main player character
    """

    def __init__(self, character_name: str):
        self.character_name = character_name
        super().__init__(f"Acted as character: {character_name}")


class AbortCommand(ControlFlowException, IOError):
    pass


class AbortWaitForInput(ControlFlowException, IOError):
    pass
