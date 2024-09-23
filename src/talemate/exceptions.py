class TalemateError(Exception):
    pass


class TalemateInterrupt(Exception):
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
    pass 


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