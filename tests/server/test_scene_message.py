"""
Unit tests for the scene_message websocket plugin.

The plugin exposes three actions that map to three distinct scene-level
operations:

- ``edit`` → ``Scene.edit_message`` (replace active version's text)
- ``append_version`` → ``Scene.append_message_version`` (grow the stack)
- ``swap_revision`` → ``Scene.set_message_active_version`` (move pointer)

The editor agent's ``cleanup_character_message`` branch in ``handle_edit``
is bypassed by stubbing the agent to ``enabled=False``; that branch is
exercised in its own agent tests and isn't the contract under test here.
"""

import pytest

from talemate.scene_message import CharacterMessage, reset_message_id
from talemate.server.scene_message import SceneMessagePlugin
from talemate.tale_mate import Scene


class _MockWebsocketHandler:
    """Minimal handler stand-in: exposes ``scene`` and a queue_put list."""

    def __init__(self, scene):
        self._scene = scene
        self.messages: list[dict] = []

    @property
    def scene(self):
        return self._scene

    def queue_put(self, data):
        self.messages.append(data)


class _DisabledEditor:
    """Stub editor agent; the plugin checks ``enabled`` and short-circuits."""

    enabled = False


@pytest.fixture(autouse=True)
def _reset_message_ids():
    reset_message_id()
    yield
    reset_message_id()


@pytest.fixture
def scene_with_message():
    """Real Scene carrying one CharacterMessage. Tests target its id."""
    scene = Scene()
    msg = CharacterMessage(message="Alice: Hello.")
    scene.history.append(msg)
    return scene, msg


@pytest.fixture
def plugin(scene_with_message, monkeypatch):
    """SceneMessagePlugin wired to a real Scene with editor cleanup disabled.

    Scene method calls are captured via spies so tests can assert which
    of the three scene-level operations was dispatched and with what
    arguments — no emit bus runs.
    """
    scene, _ = scene_with_message
    handler = _MockWebsocketHandler(scene=scene)
    plug = SceneMessagePlugin(handler)

    monkeypatch.setattr(
        "talemate.server.scene_message.instance.get_agent",
        lambda name: _DisabledEditor(),
    )

    calls: dict[str, list[dict]] = {
        "edit": [],
        "append_version": [],
        "swap_revision": [],
        "delete": [],
    }
    # Linear log capturing inter-call ordering across spies (e.g. mutate
    # then autosave). Each entry is a (name, payload) tuple.
    order: list[tuple[str, object]] = []

    def _spy_edit(message_id, text):
        entry = {"message_id": message_id, "text": text}
        calls["edit"].append(entry)
        order.append(("edit", entry))

    def _spy_append(message_id, text, source, reason=None):
        entry = {
            "message_id": message_id,
            "text": text,
            "source": source,
            "reason": reason,
        }
        calls["append_version"].append(entry)
        order.append(("append_version", entry))

    def _spy_swap(message_id, index):
        entry = {"message_id": message_id, "index": index}
        calls["swap_revision"].append(entry)
        order.append(("swap_revision", entry))

    def _spy_delete(message_id):
        calls["delete"].append(message_id)
        order.append(("delete", message_id))

    async def _spy_auto_save():
        order.append(("auto_save", None))

    monkeypatch.setattr(scene, "edit_message", _spy_edit)
    monkeypatch.setattr(scene, "append_message_version", _spy_append)
    monkeypatch.setattr(scene, "set_message_active_version", _spy_swap)
    monkeypatch.setattr(scene, "delete_message", _spy_delete)
    monkeypatch.setattr(scene, "attempt_auto_save", _spy_auto_save)
    plug._spy_calls = calls
    plug._spy_order = order
    return plug


class TestSceneMessagePluginHandleEdit:
    @pytest.mark.asyncio
    async def test_plain_edit_replaces_active_version(self, plugin, scene_with_message):
        """``handle_edit`` dispatches to ``Scene.edit_message`` — the
        active version's text is rewritten in place, no new stack
        entry is created."""
        _, msg = scene_with_message
        await plugin.handle_edit({"id": msg.id, "text": "Alice: Hi."})

        assert plugin._spy_calls["edit"] == [
            {"message_id": msg.id, "text": "Alice: Hi."}
        ]
        assert plugin._spy_calls["append_version"] == []
        assert plugin._spy_calls["swap_revision"] == []

    @pytest.mark.asyncio
    async def test_edit_drops_extra_payload_fields(self, plugin, scene_with_message):
        """``EditPayload`` only declares ``id`` and ``text``; any other
        fields a client tries to inject (legacy ``reason`` /
        ``mutation_source``, hypothetical ``source``, etc.) are dropped
        by pydantic before reaching ``Scene.edit_message``."""
        _, msg = scene_with_message
        await plugin.handle_edit(
            {
                "id": msg.id,
                "text": "Alice: Hi.",
                "source": "custom",
                "reason": "should not propagate",
            }
        )

        assert plugin._spy_calls["edit"] == [
            {"message_id": msg.id, "text": "Alice: Hi."}
        ]


class TestSceneMessagePluginHandleAppendVersion:
    @pytest.mark.asyncio
    async def test_append_forwards_source_and_reason(self, plugin, scene_with_message):
        """``handle_append_version`` dispatches to
        ``Scene.append_message_version`` with the wire-supplied
        ``source`` and optional ``reason``."""
        _, msg = scene_with_message
        await plugin.handle_append_version(
            {
                "id": msg.id,
                "text": "Alice: Hi. How are you?",
                "source": "continue",
            }
        )

        assert plugin._spy_calls["append_version"] == [
            {
                "message_id": msg.id,
                "text": "Alice: Hi. How are you?",
                "source": "continue",
                "reason": None,
            }
        ]

    @pytest.mark.asyncio
    async def test_append_defaults_source_to_custom(self, plugin, scene_with_message):
        """Omitting ``source`` defaults to ``"custom"`` — the catch-all
        bucket for client-driven mutations that don't fit the closed
        revision/regenerate/continue set."""
        _, msg = scene_with_message
        await plugin.handle_append_version(
            {"id": msg.id, "text": "Alice: rewritten", "reason": "manual override"}
        )

        assert plugin._spy_calls["append_version"] == [
            {
                "message_id": msg.id,
                "text": "Alice: rewritten",
                "source": "custom",
                "reason": "manual override",
            }
        ]


class TestSceneMessagePluginHandleSwapRevision:
    @pytest.mark.asyncio
    async def test_swap_forwards_index(self, plugin, scene_with_message):
        """``handle_swap_revision`` takes an index and forwards it to
        ``Scene.set_message_active_version`` — the canonical text follows
        the pointer rather than being set explicitly by the client."""
        _, msg = scene_with_message
        await plugin.handle_swap_revision({"id": msg.id, "index": 2})

        assert plugin._spy_calls["swap_revision"] == [
            {"message_id": msg.id, "index": 2}
        ]


class TestSceneMessagePluginHandleDelete:
    @pytest.mark.asyncio
    async def test_delete_forwards_id(self, plugin, scene_with_message):
        _, msg = scene_with_message
        await plugin.handle_delete({"id": msg.id})

        assert plugin._spy_calls["delete"] == [msg.id]


class TestSceneMessagePluginAutosavesAfterMutation:
    """All four mutation handlers must autosave AFTER their mutation so the
    change reaches the on-disk changelog — forks taken from the changelog
    UI read from disk, not from scene memory.
    """

    @pytest.mark.asyncio
    async def test_delete(self, plugin, scene_with_message):
        _, msg = scene_with_message
        await plugin.handle_delete({"id": msg.id})

        names = [name for name, _ in plugin._spy_order]
        assert names == ["delete", "auto_save"]

    @pytest.mark.asyncio
    async def test_edit(self, plugin, scene_with_message):
        _, msg = scene_with_message
        await plugin.handle_edit({"id": msg.id, "text": "Alice: Hi."})

        names = [name for name, _ in plugin._spy_order]
        assert names == ["edit", "auto_save"]

    @pytest.mark.asyncio
    async def test_append_version(self, plugin, scene_with_message):
        _, msg = scene_with_message
        await plugin.handle_append_version(
            {"id": msg.id, "text": "Alice: more.", "source": "continue"}
        )

        names = [name for name, _ in plugin._spy_order]
        assert names == ["append_version", "auto_save"]

    @pytest.mark.asyncio
    async def test_swap_revision(self, plugin, scene_with_message):
        _, msg = scene_with_message
        await plugin.handle_swap_revision({"id": msg.id, "index": 2})

        names = [name for name, _ in plugin._spy_order]
        assert names == ["swap_revision", "auto_save"]
