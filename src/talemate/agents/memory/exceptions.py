__all__ = [
    'EmbeddingsModelLoadError',
    'MemoryAgentError',
    'SetDBError'
]

class MemoryAgentError(Exception):
    pass

class SetDBError(OSError, MemoryAgentError):
    
    def __init__(self, details:str):
        super().__init__(f"Memory Agent - Failed to set up the database: {details}")

class EmbeddingsModelLoadError(ValueError, MemoryAgentError):
    
    def __init__(self, model_name:str, details:str):
        super().__init__(f"Memory Agent - Failed to load embeddings model {model_name}: {details}")