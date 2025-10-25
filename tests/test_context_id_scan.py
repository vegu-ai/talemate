import pytest
from unittest.mock import Mock, patch

from talemate.game.engine.context_id.scanner import (
    ContextIDScanResult,
    scan_text_for_context_ids,
    OpenContextIDScanCollector,
    context_id_scan_state,
)
from talemate.game.engine.context_id.base import ContextIDItem


@pytest.fixture
def mock_scene():
    """Create a mock scene for testing."""
    return Mock()


@pytest.fixture
def mock_context_id_item():
    """Create a mock ContextIDItem."""
    item = Mock(spec=ContextIDItem)
    item.context_type = "world_entry"
    item.name = "test_item"
    item.value = "test_value"
    return item


@pytest.mark.asyncio
async def test_scan_text_no_context_ids(mock_scene):
    """Test scanning text with no context IDs."""
    text = "This is regular text with no context IDs."
    result = await scan_text_for_context_ids(text, mock_scene)

    assert isinstance(result, ContextIDScanResult)
    assert len(result.resolved) == 0
    assert len(result.unresolved) == 0


@pytest.mark.asyncio
async def test_scan_text_single_context_id(mock_scene, mock_context_id_item):
    """Test scanning text with a single valid context ID."""
    text = "Update `world_entry.manual:8f54a01ce9e8` with the following changes."

    with patch(
        "talemate.game.engine.context_id.scanner.context_id_item_from_string"
    ) as mock_get:
        mock_get.return_value = mock_context_id_item
        result = await scan_text_for_context_ids(text, mock_scene)

    assert len(result.resolved) == 1
    assert len(result.unresolved) == 0
    assert result.resolved[0] == mock_context_id_item
    mock_get.assert_called_once_with("world_entry.manual:8f54a01ce9e8", mock_scene)


@pytest.mark.asyncio
async def test_scan_text_multiple_context_ids(mock_scene, mock_context_id_item):
    """Test scanning text with multiple context IDs."""
    text = "Update `world_entry.manual:8f54a01ce9e8` and `character.description:alice123` items."

    with patch(
        "talemate.game.engine.context_id.scanner.context_id_item_from_string"
    ) as mock_get:
        mock_get.return_value = mock_context_id_item
        result = await scan_text_for_context_ids(text, mock_scene)

    assert len(result.resolved) == 2
    assert len(result.unresolved) == 0
    assert mock_get.call_count == 2


@pytest.mark.asyncio
async def test_scan_text_unresolved_context_id(mock_scene):
    """Test scanning text with an unresolvable context ID."""
    text = "Update `invalid.context:nonexistent` item."

    with patch(
        "talemate.game.engine.context_id.scanner.context_id_item_from_string"
    ) as mock_get:
        mock_get.return_value = None  # Cannot resolve
        result = await scan_text_for_context_ids(text, mock_scene)

    assert len(result.resolved) == 0
    assert len(result.unresolved) == 1
    assert result.unresolved[0] == "invalid.context:nonexistent"


@pytest.mark.asyncio
async def test_scan_text_exception_handling(mock_scene):
    """Test scanning text with context ID that throws an exception."""
    text = "Update `error.context:exception` item."

    with patch(
        "talemate.game.engine.context_id.scanner.context_id_item_from_string"
    ) as mock_get:
        mock_get.side_effect = Exception("Test exception")
        result = await scan_text_for_context_ids(text, mock_scene)

    assert len(result.resolved) == 0
    assert len(result.unresolved) == 1
    assert result.unresolved[0] == "error.context:exception"


@pytest.mark.asyncio
async def test_scan_text_mixed_results(mock_scene, mock_context_id_item):
    """Test scanning text with both resolvable and unresolvable context IDs."""
    text = "Update `world_entry.manual:valid123` and `invalid.context:bad456` items."

    def mock_context_id_resolver(context_id_str, scene):
        if "valid123" in context_id_str:
            return mock_context_id_item
        return None

    with patch(
        "talemate.game.engine.context_id.scanner.context_id_item_from_string",
        side_effect=mock_context_id_resolver,
    ):
        result = await scan_text_for_context_ids(text, mock_scene)

    assert len(result.resolved) == 1
    assert len(result.unresolved) == 1
    assert result.resolved[0] == mock_context_id_item
    assert result.unresolved[0] == "invalid.context:bad456"


@pytest.mark.asyncio
async def test_scan_text_various_patterns(mock_scene, mock_context_id_item):
    """Test scanning text with various context ID patterns."""
    text = """
    Various patterns:
    - `simple:abc123`
    - `dotted.type:path.to.item`
    - `underscore_type:item_name`
    - `complex.nested.type:deep.nested.path.item`
    """

    with patch(
        "talemate.game.engine.context_id.scanner.context_id_item_from_string"
    ) as mock_get:
        mock_get.return_value = mock_context_id_item
        result = await scan_text_for_context_ids(text, mock_scene)

    assert len(result.resolved) == 4
    assert len(result.unresolved) == 0
    assert mock_get.call_count == 4


@pytest.mark.asyncio
async def test_scan_text_ignore_non_backtick_patterns(mock_scene):
    """Test that non-backtick patterns are ignored."""
    text = """
    Should ignore these:
    - world_entry.manual:8f54a01ce9e8 (no backticks)
    - 'world_entry.manual:8f54a01ce9e8' (single quotes)
    - "world_entry.manual:8f54a01ce9e8" (double quotes)
    But match this: `world_entry.manual:8f54a01ce9e8`
    """

    with patch(
        "talemate.game.engine.context_id.scanner.context_id_item_from_string"
    ) as mock_get:
        mock_get.return_value = None
        await scan_text_for_context_ids(text, mock_scene)

    assert mock_get.call_count == 1
    mock_get.assert_called_once_with("world_entry.manual:8f54a01ce9e8", mock_scene)


@pytest.mark.asyncio
async def test_scan_text_ignore_invalid_patterns(mock_scene):
    """Test that invalid patterns are ignored by regex."""
    text = """
    Invalid patterns that should be ignored:
    - `:invalid` (no prefix)
    - `invalid:` (no suffix)
    - `123invalid:abc` (starts with number)
    - `valid-name:abc` (contains hyphen)
    Valid pattern: `valid_name:abc123`
    """

    with patch(
        "talemate.game.engine.context_id.scanner.context_id_item_from_string"
    ) as mock_get:
        mock_get.return_value = None
        await scan_text_for_context_ids(text, mock_scene)

    assert mock_get.call_count == 1
    mock_get.assert_called_once_with("valid_name:abc123", mock_scene)


@pytest.mark.asyncio
async def test_context_id_scan_result_model():
    """Test the ContextIDScanResult Pydantic model."""
    # Test empty initialization
    result = ContextIDScanResult()
    assert result.resolved == []
    assert result.unresolved == []

    # Test with data
    mock_item = Mock(spec=ContextIDItem)
    result = ContextIDScanResult(resolved=[mock_item], unresolved=["unresolved_id"])
    assert len(result.resolved) == 1
    assert len(result.unresolved) == 1
    assert result.resolved[0] == mock_item
    assert result.unresolved[0] == "unresolved_id"


@pytest.mark.asyncio
async def test_scan_text_duplicate_context_ids(mock_scene, mock_context_id_item):
    """Test scanning text with duplicate context IDs."""
    text = "Update `world_entry:item1` and then update `world_entry:item1` again."

    with patch(
        "talemate.game.engine.context_id.scanner.context_id_item_from_string"
    ) as mock_get:
        mock_get.return_value = mock_context_id_item
        result = await scan_text_for_context_ids(text, mock_scene)

    # Should find both instances
    assert len(result.resolved) == 2
    assert len(result.unresolved) == 0
    assert mock_get.call_count == 2


@pytest.mark.asyncio
async def test_scan_text_context_ids_with_spaces(mock_scene, mock_context_id_item):
    """Test scanning text with context IDs containing spaces after colon."""
    text = "Update `world_entry:hello world` and `character:john doe smith` items."

    with patch(
        "talemate.game.engine.context_id.scanner.context_id_item_from_string"
    ) as mock_get:
        mock_get.return_value = mock_context_id_item
        result = await scan_text_for_context_ids(text, mock_scene)

    assert len(result.resolved) == 2
    assert len(result.unresolved) == 0
    assert mock_get.call_count == 2
    # Verify the exact strings passed to the resolver
    mock_get.assert_any_call("world_entry:hello world", mock_scene)
    mock_get.assert_any_call("character:john doe smith", mock_scene)


@pytest.mark.asyncio
async def test_scan_text_context_ids_mixed_spaces_and_no_spaces(
    mock_scene, mock_context_id_item
):
    """Test scanning text with both spaced and non-spaced context IDs."""
    text = "Update `world_entry:no_spaces` and `character:with spaces` items."

    with patch(
        "talemate.game.engine.context_id.scanner.context_id_item_from_string"
    ) as mock_get:
        mock_get.return_value = mock_context_id_item
        result = await scan_text_for_context_ids(text, mock_scene)

    assert len(result.resolved) == 2
    assert len(result.unresolved) == 0
    assert mock_get.call_count == 2
    mock_get.assert_any_call("world_entry:no_spaces", mock_scene)
    mock_get.assert_any_call("character:with spaces", mock_scene)


def test_open_context_id_scan_collector_init():
    """Test OpenContextIDScanCollector initialization."""
    collector = OpenContextIDScanCollector()
    assert isinstance(collector.context_ids, set)
    assert len(collector.context_ids) == 0


def test_open_context_id_scan_collector_context_manager():
    """Test OpenContextIDScanCollector as context manager."""
    collector = OpenContextIDScanCollector()

    # Initially no context variable should be set
    assert context_id_scan_state.get(None) is None

    # Test entering context
    with collector:
        assert context_id_scan_state.get() is collector
        assert isinstance(collector.context_ids, set)

    # Context should be reset after exiting
    assert context_id_scan_state.get(None) is None


def test_open_context_id_scan_collector_manual_enter_exit():
    """Test OpenContextIDScanCollector manual enter/exit."""
    collector = OpenContextIDScanCollector()

    # Initially no context variable should be set
    assert context_id_scan_state.get(None) is None

    # Manual enter
    result = collector.__enter__()
    assert result is collector
    assert context_id_scan_state.get() is collector

    # Manual exit
    collector.__exit__(None, None, None)
    assert context_id_scan_state.get(None) is None


def test_open_context_id_scan_collector_nested_contexts():
    """Test nested OpenContextIDScanCollector contexts."""
    collector1 = OpenContextIDScanCollector()
    collector2 = OpenContextIDScanCollector()

    assert context_id_scan_state.get(None) is None

    with collector1:
        assert context_id_scan_state.get() is collector1
        collector1.context_ids.add("test1")

        with collector2:
            assert context_id_scan_state.get() is collector2
            collector2.context_ids.add("test2")

        # Should restore to collector1 after collector2 exits
        assert context_id_scan_state.get() is collector1
        assert "test1" in collector1.context_ids
        assert "test2" in collector2.context_ids

    # Should be None after both exit
    assert context_id_scan_state.get(None) is None


def test_open_context_id_scan_collector_exception_handling():
    """Test OpenContextIDScanCollector handles exceptions properly."""
    collector = OpenContextIDScanCollector()

    assert context_id_scan_state.get(None) is None

    try:
        with collector:
            assert context_id_scan_state.get() is collector
            raise ValueError("Test exception")
    except ValueError:
        pass

    # Context should still be reset even after exception
    assert context_id_scan_state.get(None) is None


@pytest.mark.asyncio
async def test_scan_text_with_collector_context(mock_scene, mock_context_id_item):
    """Test scanning text while in OpenContextIDScanCollector context."""
    text = "Update `world_entry.manual:8f54a01ce9e8` with changes."
    collector = OpenContextIDScanCollector()

    # Mock the context ID item to have a context_id attribute
    mock_context_id_item.context_id = "world_entry.manual:8f54a01ce9e8"

    with patch(
        "talemate.game.engine.context_id.scanner.context_id_item_from_string"
    ) as mock_get:
        mock_get.return_value = mock_context_id_item

        with collector:
            result = await scan_text_for_context_ids(text, mock_scene)

            # Verify scan result
            assert len(result.resolved) == 1
            assert len(result.unresolved) == 0

            # Verify collector captured the context ID
            assert "world_entry.manual:8f54a01ce9e8" in collector.context_ids


@pytest.mark.asyncio
async def test_scan_text_multiple_items_with_collector(mock_scene):
    """Test scanning text with multiple context IDs while using collector."""
    text = "Update `world_entry:item1` and `character:alice` items."
    collector = OpenContextIDScanCollector()

    # Create mock context items with different IDs
    mock_item1 = Mock(spec=ContextIDItem)
    mock_item1.context_id = "world_entry:item1"
    mock_item2 = Mock(spec=ContextIDItem)
    mock_item2.context_id = "character:alice"

    def mock_resolver(context_id_str, scene):
        if "item1" in context_id_str:
            return mock_item1
        elif "alice" in context_id_str:
            return mock_item2
        return None

    with patch(
        "talemate.game.engine.context_id.scanner.context_id_item_from_string",
        side_effect=mock_resolver,
    ):
        with collector:
            result = await scan_text_for_context_ids(text, mock_scene)

            # Verify scan result
            assert len(result.resolved) == 2
            assert len(result.unresolved) == 0

            # Verify collector captured both context IDs
            assert "world_entry:item1" in collector.context_ids
            assert "character:alice" in collector.context_ids
            assert len(collector.context_ids) == 2


@pytest.mark.asyncio
async def test_scan_text_without_collector_context(mock_scene, mock_context_id_item):
    """Test scanning text without OpenContextIDScanCollector context."""
    text = "Update `world_entry.manual:8f54a01ce9e8` with changes."

    with patch(
        "talemate.game.engine.context_id.scanner.context_id_item_from_string"
    ) as mock_get:
        mock_get.return_value = mock_context_id_item

        # Scan without collector context
        result = await scan_text_for_context_ids(text, mock_scene)

        # Should still work normally
        assert len(result.resolved) == 1
        assert len(result.unresolved) == 0

        # But no collector should be active
        assert context_id_scan_state.get(None) is None


@pytest.mark.asyncio
async def test_collector_context_ids_accumulate(mock_scene):
    """Test that collector accumulates context IDs across multiple scans."""
    collector = OpenContextIDScanCollector()

    # Mock context items
    mock_item1 = Mock(spec=ContextIDItem)
    mock_item1.context_id = "world_entry:item1"
    mock_item2 = Mock(spec=ContextIDItem)
    mock_item2.context_id = "character:alice"

    def mock_resolver(context_id_str, scene):
        if "item1" in context_id_str:
            return mock_item1
        elif "alice" in context_id_str:
            return mock_item2
        return None

    with patch(
        "talemate.game.engine.context_id.scanner.context_id_item_from_string",
        side_effect=mock_resolver,
    ):
        with collector:
            # First scan
            await scan_text_for_context_ids("Update `world_entry:item1`", mock_scene)
            assert len(collector.context_ids) == 1
            assert "world_entry:item1" in collector.context_ids

            # Second scan with different item
            await scan_text_for_context_ids("Update `character:alice`", mock_scene)
            assert len(collector.context_ids) == 2
            assert "world_entry:item1" in collector.context_ids
            assert "character:alice" in collector.context_ids

            # Third scan with duplicate - should not increase count
            await scan_text_for_context_ids(
                "Update `world_entry:item1` again", mock_scene
            )
            assert len(collector.context_ids) == 2  # Still 2, not 3
