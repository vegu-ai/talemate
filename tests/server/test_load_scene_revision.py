"""Opening a scene at a changelog revision is not reachable.

The timeline's only action is forking to a new save; the load route that
reconstructed a revision into the live scene is gone, so nothing but a fork
can put reconstructed data in front of the user.
"""

import inspect

import pytest

from talemate.server.websocket_server import WebsocketHandler


def test_load_scene_route_takes_no_revision():
    params = inspect.signature(WebsocketHandler.load_scene).parameters
    assert "rev" not in params


def test_load_scene_rejects_a_revision_argument():
    with pytest.raises(TypeError):
        WebsocketHandler.load_scene(object(), "scene.json", rev=1)
