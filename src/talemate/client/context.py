"""
Context managers for various client-side operations.
"""

from contextvars import ContextVar
from pydantic import BaseModel, Field

__all__ = [
    'context_data',
    'client_context_attribute',
    'ContextModel',
]

class ContextModel(BaseModel):
    """
    Pydantic model for the context data.
    """
    nuke_repetition: float = Field(0.0, ge=0.0, le=3.0)

# Define the context variable as an empty dictionary
context_data = ContextVar('context_data', default=ContextModel().dict())

def client_context_attribute(name, default=None):
    """
    Get the value of the context variable `context_data` for the given key.
    """
    # Get the current context data
    data = context_data.get()
    # Return the value of the key if it exists, otherwise return the default value
    return data.get(name, default)



class ClientContext:
    """
    A context manager to set values to the context variable `context_data`.
    """

    def __init__(self, **kwargs):
        """
        Initialize the context manager with the key-value pairs to be set.
        """
        # Validate the data with the Pydantic model
        self.values = ContextModel(**kwargs).dict()
        self.tokens = {}

    def __enter__(self):
        """
        Set the key-value pairs to the context variable `context_data` when entering the context.
        """
        # Get the current context data
        data = context_data.get()
        # For each key-value pair, save the current value of the key (if it exists) and set the new value
        for key, value in self.values.items():
            self.tokens[key] = data.get(key, None)
            data[key] = value
        # Update the context data
        context_data.set(data)

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Reset the context variable `context_data` to its previous values when exiting the context.
        """
        # Get the current context data
        data = context_data.get()
        # For each key, if a previous value exists, reset it. Otherwise, remove the key
        for key in self.values.keys():
            if self.tokens[key] is not None:
                data[key] = self.tokens[key]
            else:
                data.pop(key, None)
        # Update the context data
        context_data.set(data)