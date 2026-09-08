import importlib
import pkgutil

import talemate.client as client_package
from talemate.client.registry import CLIENT_CLASSES
from talemate.config.schema import Client

CONTEXT_LENGTH_FLOOR = 16384


def _registered_client_classes():
    for module_info in pkgutil.iter_modules(client_package.__path__):
        importlib.import_module(f"talemate.client.{module_info.name}")
    return dict(CLIENT_CLASSES)


def _default_context_length(client_class):
    defaults = client_class.Meta().defaults
    if "max_token_length" in type(defaults).model_fields:
        return defaults.max_token_length
    return Client.model_fields["max_token_length"].default


def test_every_registered_client_type_defaults_to_the_context_floor_or_more():
    classes = _registered_client_classes()
    for expected in ("koboldcpp", "groq", "openai_compat", "ollama", "openrouter"):
        assert expected in classes
    below = {
        client_type: _default_context_length(cls)
        for client_type, cls in classes.items()
        if _default_context_length(cls) < CONTEXT_LENGTH_FLOOR
    }
    assert below == {}


def test_saved_client_config_without_a_value_defaults_to_the_floor():
    assert Client(type="koboldcpp", name="k").max_token_length == CONTEXT_LENGTH_FLOOR


def test_a_saved_value_is_kept():
    assert (
        Client(type="koboldcpp", name="k", max_token_length=8192).max_token_length
        == 8192
    )
