"""
Context managers for various client-side operations.
"""

from contextvars import ContextVar
from copy import deepcopy

import structlog
from pydantic import BaseModel, Field

__all__ = [
    "context_data",
    "client_context_attribute",
    "ContextModel",
]

log = structlog.get_logger()


def model_to_dict_without_defaults(model_instance):
    model_dict = model_instance.dict()
    for field_name, field in model_instance.__class__.__fields__.items():
        if field.default == model_dict.get(field_name):
            del model_dict[field_name]
        # special case for conversation context, dont copy if talking_character is None
        if field_name == "conversation" and model_dict.get(field_name).get("talking_character") is None:
            del model_dict[field_name]
    return model_dict


class ConversationContext(BaseModel):
    talking_character: str = None
    other_characters: list[str] = Field(default_factory=list)


class ContextModel(BaseModel):
    """
    Pydantic model for the context data.
    """

    nuke_repetition: float = Field(0.0, ge=0.0, le=3.0)
    conversation: ConversationContext = Field(default_factory=ConversationContext)
    length: int = 96
    inference_preset: str = None


# Define the context variable as an empty dictionary
context_data = ContextVar("context_data", default=ContextModel().model_dump())


def client_context_attribute(name, default=None):
    """
    Get the value of the context variable `context_data` for the given key.
    """
    # Get the current context data
    data = context_data.get()
    # Return the value of the key if it exists, otherwise return the default value
    return data.get(name, default)


def set_client_context_attribute(name, value):
    """
    Set the value of the context variable `context_data` for the given key.
    """
    # Get the current context data
    data = context_data.get()
    # Set the value of the key
    data[name] = value


def set_conversation_context_attribute(name, value):
    """
    Set the value of the context variable `context_data.conversation` for the given key.
    """
    # Get the current context data
    data = context_data.get()
    # Set the value of the key
    data["conversation"][name] = value


class ClientContext:
    """
    A context manager to set values to the context variable `context_data`.
    """

    def __init__(self, **kwargs):
        """
        Initialize the context manager with the key-value pairs to be set.
        """
        # Validate the data with the Pydantic model
        self.values = model_to_dict_without_defaults(ContextModel(**kwargs))

    def __enter__(self):
        """
        Set the key-value pairs to the context variable `context_data` when entering the context.
        """
        # Get the current context data

        data = deepcopy(context_data.get()) if context_data.get() else {}
        data.update(self.values)

        # Update the context data
        self.token = context_data.set(data)

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Reset the context variable `context_data` to its previous values when exiting the context.
        """

        context_data.reset(self.token)
