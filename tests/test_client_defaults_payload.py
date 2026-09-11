"""The add-client payload the settings UI builds must validate for every client type.

`AppSettingsClients.addClient` seeds a new client from the `Meta().defaults`
shipped in the `client_types` message and nothing else — the backend model
fills in the rest. These tests pin that contract from the backend side: for
every registered client type, `{**meta.defaults, type, name, enabled}` has to
survive `Config` validation, which routes through the per-type `config_cls`
(`validate_client_type`).

The regression this guards: seeding declared `extra_fields` that have no entry
in `Meta.defaults` with an explicit `null` (e.g. openrouter's
`concurrent_inference_enabled`, typed `bool` on its `ClientConfig`) fails
validation for the WHOLE config, so saving the app settings after adding a
client was refused with no way forward.
"""

from __future__ import annotations

from types import NoneType
from typing import get_args

import pydantic
import pytest

import talemate.client  # noqa: F401  - registers the client classes
from talemate.client.registry import CLIENT_CLASSES
from talemate.config.schema import Config


CLIENT_TYPES = sorted(CLIENT_CLASSES.keys())


def add_client_payload(client_type: str) -> dict:
    """The payload the settings UI ships for a freshly added client."""
    meta = CLIENT_CLASSES[client_type].Meta().model_dump()
    return {
        **(meta.get("defaults") or {}),
        "type": client_type,
        "name": f"{meta.get('name_prefix') or client_type}",
        "enabled": True,
    }


def _annotation_allows_none(annotation) -> bool:
    return annotation is NoneType or any(
        _annotation_allows_none(arg) for arg in get_args(annotation)
    )


def _null_rejection_cases():
    cases = []
    for client_type in CLIENT_TYPES:
        client_cls = CLIENT_CLASSES[client_type]
        meta = client_cls.Meta().model_dump()
        defaults = meta.get("defaults") or {}
        config_cls = getattr(client_cls, "config_cls", None)
        if not config_cls:
            continue
        non_nullable = [
            name
            for name in (meta.get("extra_fields") or {})
            if name not in defaults
            and name in config_cls.model_fields
            and not _annotation_allows_none(config_cls.model_fields[name].annotation)
        ]
        if non_nullable:
            cases.append(pytest.param(client_type, non_nullable, id=client_type))
    return cases


NULL_REJECTION_CASES = _null_rejection_cases()


@pytest.mark.parametrize("client_type", CLIENT_TYPES)
def test_add_client_payload_validates(client_type: str):
    config = Config(clients={"test-client": add_client_payload(client_type)})
    client = config.clients["test-client"]
    assert client.type == client_type
    assert client.enabled is True


@pytest.mark.parametrize("client_type", CLIENT_TYPES)
def test_extra_fields_without_defaults_are_omittable(client_type: str):
    """Every declared extra field must be valid when simply left out.

    The UI cannot invent a value for an extra field that `Meta.defaults` does
    not carry, so the model has to supply one. A field that is required with no
    default would make the add-client flow unsatisfiable.
    """
    client_cls = CLIENT_CLASSES[client_type]
    meta = client_cls.Meta().model_dump()
    defaults = meta.get("defaults") or {}
    missing = [
        name for name in (meta.get("extra_fields") or {}) if name not in defaults
    ]

    payload = add_client_payload(client_type)
    for name in missing:
        assert name not in payload

    config = Config(clients={"test-client": payload})
    client = config.clients["test-client"]
    for name in missing:
        # resolved by the model rather than by the UI
        assert hasattr(client, name) or name not in client.model_fields_set


def test_clients_with_non_nullable_extra_fields_are_found():
    assert NULL_REJECTION_CASES


@pytest.mark.parametrize(("client_type", "non_nullable"), NULL_REJECTION_CASES)
def test_null_seeded_extra_fields_are_rejected(
    client_type: str, non_nullable: list[str]
):
    """Documents WHY the UI must omit rather than null-seed unknown extras.

    Not every client type has a non-nullable extra field, so this only asserts
    the failure where one exists — the point is that null-seeding is unsafe as
    a class, which is what the previous implementation did for all types.
    """
    payload = add_client_payload(client_type)
    for name in non_nullable:
        payload[name] = None

    with pytest.raises(pydantic.ValidationError):
        Config(clients={"test-client": payload})


def test_openrouter_concurrent_inference_is_the_known_case():
    """Pin the specific field that broke the add-client flow."""
    meta = CLIENT_CLASSES["openrouter"].Meta().model_dump()
    assert "concurrent_inference_enabled" in meta["extra_fields"]
    assert "concurrent_inference_enabled" not in (meta.get("defaults") or {})

    config = Config(clients={"test-client": add_client_payload("openrouter")})
    assert config.clients["test-client"].concurrent_inference_enabled is True
