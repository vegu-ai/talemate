__all__ = [
    "VisualAgentError",
    "ImageEditNotAvailableError",
    "TextToImageNotAvailableError",
    "ImageAnalysisNotAvailableError",
]


class VisualAgentError(Exception):
    pass


class ImageEditNotAvailableError(VisualAgentError):
    pass


class TextToImageNotAvailableError(VisualAgentError):
    pass


class ImageAnalysisNotAvailableError(VisualAgentError):
    pass
