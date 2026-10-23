"""
A failed image generation names its reason where the user sees it: the status
notification. Before #734 it only said "Image generation failed." and the
reason reached the backend log alone.
"""

import httpx
import pytest

import talemate.agents.visual.generation as generation_module
from talemate.agents.visual.agent import VisualAgent


@pytest.fixture
def emits(monkeypatch):
    sent = []
    monkeypatch.setattr(
        generation_module,
        "emit",
        lambda typ, message=None, **kwargs: sent.append((typ, message, kwargs)),
    )
    return sent


@pytest.mark.parametrize(
    "error, reason",
    [
        (
            ValueError(
                "inclusionai/ming-image-0.1-design does not accept reference images"
            ),
            "inclusionai/ming-image-0.1-design does not accept reference images",
        ),
        # an httpx timeout carries an empty str()
        (httpx.ReadTimeout(""), "ReadTimeout"),
    ],
)
async def test_a_generation_failure_names_its_reason(emits, error, reason):
    await VisualAgent().on_image_generation_error(error)

    assert emits == [
        (
            "image_generation_failed",
            None,
            {"websocket_passthrough": True, "data": {"error": reason}},
        ),
        ("status", f"Image generation failed: {reason}", {"status": "error"}),
    ]


async def test_a_long_error_body_becomes_one_short_line_in_the_status(emits):
    page = "<!DOCTYPE html>\n<html><body>" + "x" * 4600 + "</body></html>"
    reason = f"OpenRouter image request failed (HTTP 502): {page}"

    await VisualAgent().on_image_generation_error(ValueError(reason))

    failed, status = emits
    # the failure event and the log keep the whole reason
    assert failed[2]["data"]["error"] == reason
    assert status[1] == (
        "Image generation failed: "
        "OpenRouter image request failed (HTTP 502): <!DOCTYPE html>"
    )


def test_the_status_reason_cuts_a_long_line():
    cut = generation_module.status_reason("a" * 1000)

    assert len(cut) == generation_module.STATUS_REASON_LIMIT
    assert cut.endswith("…")
    assert generation_module.status_reason("a short reason") == "a short reason"
