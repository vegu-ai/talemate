import pytest
from talemate.client.base import ClientBase

@pytest.mark.parametrize(
    "kind",
    [
        "narrate",
        "story",
        "director",
        "create",
        "roleplay",
        "conversation",
        "editor",
        "world_state",
        "analyze_freeform",
        "analyst",
        "analyze",
        "summarize",
    ],
)
def test_system_message(kind):
    
    client = ClientBase()
    
    assert client.get_system_message(kind) is not None
    
    assert "crude" in client.get_system_message(kind)
    
    client.decensor_enabled = False
    
    assert client.get_system_message(kind) is not None
    
    assert "crude" not in client.get_system_message(kind)
    