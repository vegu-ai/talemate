import pytest
from talemate.util.path import split_state_path, get_path_parent
from talemate.game.engine.nodes.core import InputValueError


class TestSplitStatePath:
    """Tests for split_state_path function."""

    def test_simple_path(self):
        """Test splitting a simple path."""
        assert split_state_path("a/b/c") == ["a", "b", "c"]

    def test_single_segment(self):
        """Test splitting a single segment path."""
        assert split_state_path("a") == ["a"]

    def test_leading_slash(self):
        """Test path with leading slash."""
        assert split_state_path("/a/b/c") == ["a", "b", "c"]

    def test_trailing_slash(self):
        """Test path with trailing slash."""
        assert split_state_path("a/b/c/") == ["a", "b", "c"]

    def test_both_slashes(self):
        """Test path with both leading and trailing slashes."""
        assert split_state_path("/a/b/c/") == ["a", "b", "c"]

    def test_multiple_slashes(self):
        """Test path with multiple consecutive slashes."""
        assert split_state_path("a//b///c") == ["a", "b", "c"]

    def test_empty_string(self):
        """Test that empty string raises ValueError."""
        with pytest.raises(ValueError, match="Path name cannot be empty"):
            split_state_path("")

    def test_only_slashes(self):
        """Test that string with only slashes raises ValueError."""
        with pytest.raises(ValueError, match="Path name cannot be empty"):
            split_state_path("///")

    def test_whitespace_handling(self):
        """Test that whitespace is preserved in segments."""
        assert split_state_path("a/b c/d") == ["a", "b c", "d"]


class TestGetPathParent:
    """Tests for get_path_parent function."""

    def test_simple_path_create(self):
        """Test creating a simple path."""
        container = {}
        parts = ["a", "b", "c"]
        parent, leaf = get_path_parent(container, parts, create=True)

        assert leaf == "c"
        assert isinstance(parent, dict)
        assert "a" in container
        assert isinstance(container["a"], dict)
        assert "b" in container["a"]
        assert isinstance(container["a"]["b"], dict)

    def test_simple_path_no_create(self):
        """Test traversing existing path without creating."""
        container = {"a": {"b": {"c": 42}}}
        parts = ["a", "b", "c"]
        parent, leaf = get_path_parent(container, parts, create=False)

        assert leaf == "c"
        assert parent == container["a"]["b"]
        assert parent["c"] == 42

    def test_missing_path_no_create(self):
        """Test missing path without create returns None."""
        container = {}
        parts = ["a", "b", "c"]
        parent, leaf = get_path_parent(container, parts, create=False)

        assert parent is None
        assert leaf == "c"

    def test_partial_path_no_create(self):
        """Test partial existing path without create returns None."""
        container = {"a": {}}
        parts = ["a", "b", "c"]
        parent, leaf = get_path_parent(container, parts, create=False)

        assert parent is None
        assert leaf == "c"

    def test_single_segment_create(self):
        """Test single segment path with create."""
        container = {}
        parts = ["a"]
        parent, leaf = get_path_parent(container, parts, create=True)

        assert leaf == "a"
        assert parent == container

    def test_single_segment_no_create(self):
        """Test single segment path."""
        container = {"a": 42}
        parts = ["a"]
        parent, leaf = get_path_parent(container, parts, create=False)

        assert leaf == "a"
        assert parent == container

    def test_conflict_non_dict_intermediate(self):
        """Test that non-dict intermediate raises error when create=True."""
        container = {"a": 5}  # 'a' is not a dict
        parts = ["a", "b", "c"]

        with pytest.raises(
            ValueError, match="Path segment 'a' exists but is not a dictionary"
        ):
            get_path_parent(container, parts, create=True)

    def test_conflict_non_dict_intermediate_with_node(self):
        """Test that non-dict intermediate raises InputValueError when node provided."""
        from talemate.game.engine.nodes.core import Node

        # Create a mock node
        mock_node = Node(title="Test Node")

        container = {"a": 5}  # 'a' is not a dict
        parts = ["a", "b", "c"]

        with pytest.raises(InputValueError):
            get_path_parent(container, parts, create=True, node_for_errors=mock_node)

    def test_conflict_deep_path(self):
        """Test conflict in deeper path."""
        container = {"a": {"b": 5}}  # 'b' is not a dict
        parts = ["a", "b", "c"]

        with pytest.raises(
            ValueError, match="Path segment 'a/b' exists but is not a dictionary"
        ):
            get_path_parent(container, parts, create=True)

    def test_empty_parts(self):
        """Test that empty parts list raises ValueError."""
        container = {}

        with pytest.raises(ValueError, match="Path parts cannot be empty"):
            get_path_parent(container, [], create=True)

    def test_nested_creation(self):
        """Test creating deeply nested structure."""
        container = {}
        parts = ["level1", "level2", "level3", "level4", "key"]
        parent, leaf = get_path_parent(container, parts, create=True)

        assert leaf == "key"
        assert isinstance(parent, dict)
        assert container["level1"]["level2"]["level3"]["level4"] == parent

    def test_existing_intermediate_dicts(self):
        """Test that existing dicts are reused."""
        container = {"a": {"b": {"existing": "value"}}}
        parts = ["a", "b", "c"]
        parent, leaf = get_path_parent(container, parts, create=True)

        assert leaf == "c"
        assert parent == container["a"]["b"]
        # Existing key should still be there
        assert parent["existing"] == "value"
        # New key can be set
        parent[leaf] = "new_value"
        assert container["a"]["b"]["c"] == "new_value"

    def test_dict_like_container(self):
        """Test with dict-like container that has get method."""

        class DictLike:
            def __init__(self):
                self._data = {}

            def get(self, key, default=None):
                return self._data.get(key, default)

            def __setitem__(self, key, value):
                self._data[key] = value

            def __getitem__(self, key):
                return self._data[key]

            def __contains__(self, key):
                return key in self._data

        container = DictLike()
        parts = ["a", "b", "c"]
        parent, leaf = get_path_parent(container, parts, create=True)

        assert leaf == "c"
        assert isinstance(parent, dict)
        assert "a" in container._data
        assert isinstance(container._data["a"], dict)

    def test_no_get_method_container(self):
        """Test with container that doesn't have get method."""
        container = {}
        parts = ["a", "b", "c"]
        parent, leaf = get_path_parent(container, parts, create=True)

        assert leaf == "c"
        assert isinstance(parent, dict)
