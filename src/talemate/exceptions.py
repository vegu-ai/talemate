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


class RenderPromptError(TalemateError):
    """
    Exception to raise when there is an error rendering a prompt
    """
    
    pass


class LLMAccuracyError(TalemateError):
    """
    Exception to raise when the LLM response is not processable
    """
    
    def __init__(self, message:str, model_name:str):
        super().__init__(f"{model_name} - {message}")
        self.model_name = model_name