import pytest
from unittest.mock import patch, AsyncMock

from talemate.game.engine.context_id import (
    ContextID,
    CharacterDescriptionContextID,
    CharacterAttributeContextID,
    CharacterDetailContextID,
    WorldEntryContextID,
    WorldEntryManualContextID,
    StaticHistoryEntryContextID,
    DynamicHistoryEntryContextID,
    get_context_id_type,
    context_id_from_string,
    context_id_from_object,
    context_id_item_from_string,
    context_id_handler_from_string,
    compress_name,
    CONTEXT_ID_TYPES,
    CONTEXT_ID_PATH_HANDLERS,
    ContextIDHandlerError,
    ContextIDNoHandlerFound,
    CharacterContext,
)
from talemate.game.engine.context_id.story_configuration import (
    DirectorInstructionsContextID,
    StoryConfigurationContext,
    StoryConfigurationContextItem,
)
from talemate.character import Character
from talemate.history import HistoryEntry
from talemate.world_state import ManualContext


@pytest.mark.parametrize(
    "path, expected_path_str",
    [
        (["test"], "context:test"),
        (["test", "path"], "context:test.path"),
        (["nested", "test", "path"], "context:nested.test.path"),
        ([], "context:"),
    ],
)
def test_context_id_basic_functionality(path, expected_path_str):
    """Test basic ContextID functionality with various paths."""
    context_id = ContextID(path=path)
    assert context_id.path == path
    assert context_id.context_type == "context"
    assert context_id.path_to_str == expected_path_str
    assert context_id.id == expected_path_str
    assert str(context_id) == expected_path_str


@pytest.mark.parametrize(
    "path",
    [
        ["test"],
        ["test", "path"],
        ["nested", "test", "path"],
    ],
)
def test_context_id_class_methods(path):
    """Test ContextID class methods."""
    context_id_make = ContextID.make(path)

    assert context_id_make.path == path


@pytest.mark.parametrize(
    "character_input, expected_character",
    [
        ("TestChar", "TestChar"),
        (Character(name="RealChar"), "RealChar"),
    ],
)
def test_character_description_context_id(character_input, expected_character):
    """Test CharacterDescriptionContextID creation."""
    context_id = CharacterDescriptionContextID.make(character_input)
    assert context_id.character == expected_character
    assert context_id.path == [expected_character, "description"]
    assert context_id.context_type == "character.description"
    assert (
        context_id.path_to_str
        == f"character.description:{expected_character}.description"
    )


@pytest.mark.parametrize(
    "character_input, attribute, expected_character",
    [
        ("TestChar", "strength", "TestChar"),
        (Character(name="RealChar"), "intelligence", "RealChar"),
        ("Player", "dexterity", "Player"),
    ],
)
def test_character_attribute_context_id(character_input, attribute, expected_character):
    """Test CharacterAttributeContextID creation."""
    context_id = CharacterAttributeContextID.make(character_input, attribute)
    assert context_id.character == expected_character
    assert context_id.attribute == attribute
    # Path should use compressed attribute name
    assert context_id.path == [expected_character, compress_name(attribute)]
    assert context_id.context_type == "character.attribute"


@pytest.mark.parametrize(
    "character_input, detail, expected_character",
    [
        ("TestChar", "appearance", "TestChar"),
        (Character(name="RealChar"), "personality", "RealChar"),
        ("Player", "background", "Player"),
    ],
)
def test_character_detail_context_id(character_input, detail, expected_character):
    """Test CharacterDetailContextID creation."""
    context_id = CharacterDetailContextID.make(character_input, detail)
    assert context_id.character == expected_character
    assert context_id.detail == detail
    # Path should use compressed detail name
    assert context_id.path == [expected_character, compress_name(detail)]
    assert context_id.context_type == "character.detail"


@pytest.mark.parametrize(
    "entry_id, expected_path",
    [
        ("test_entry_123", []),
        ("world_item_456", []),
    ],
)
def test_world_entry_context_id(entry_id, expected_path):
    """Test WorldEntryContextID direct creation (base class)."""
    context_id = WorldEntryContextID(entry_id=entry_id, path=expected_path)
    assert context_id.entry_id == entry_id
    assert context_id.path == expected_path
    assert context_id.context_type == "world_entry"


@pytest.mark.parametrize(
    "entry_input, expected_entry_id",
    [
        ("test_entry", "test_entry"),
        (ManualContext(id="manual_123", text="test text"), "manual_123"),
    ],
)
def test_world_entry_manual_context_id(entry_input, expected_entry_id):
    """Test WorldEntryManualContextID creation with string or ManualContext."""
    context_id = WorldEntryManualContextID.make(entry_input)
    assert context_id.context_type == "world_entry.manual"
    assert context_id.entry_id == expected_entry_id
    # Path should use compressed entry ID
    assert context_id.path == [compress_name(expected_entry_id)]


@pytest.mark.parametrize(
    "entry_id, layer, expected_path",
    [
        ("entry_123", 0, ["layer", "0", "id", "entry_123"]),
        ("entry_456", 5, ["layer", "5", "id", "entry_456"]),
        ("entry_789", 10, ["layer", "10", "id", "entry_789"]),
    ],
)
def test_dynamic_history_entry_context_id(entry_id, layer, expected_path):
    """Test DynamicHistoryEntryContextID creation."""
    entry = HistoryEntry(text="test", ts="PT1S", index=0, layer=layer, id=entry_id)
    context_id = DynamicHistoryEntryContextID.make(entry)
    assert context_id.entry_id == entry_id
    assert context_id.layer == layer
    assert context_id.path == expected_path
    assert context_id.context_type == "history_entry.dynamic"


@pytest.mark.parametrize(
    "entry_id",
    [
        "entry_123",
        "static_entry_456",
    ],
)
def test_static_history_entry_context_id(entry_id):
    """Test StaticHistoryEntryContextID creation."""
    entry = HistoryEntry(text="test", ts="PT1S", index=0, layer=0, id=entry_id)
    context_id = StaticHistoryEntryContextID.make(entry)
    assert context_id.entry_id == entry_id
    assert context_id.path == [entry_id]
    assert context_id.context_type == "history_entry.static"


@pytest.mark.parametrize(
    "context_type, expected_class",
    [
        ("character.description", CharacterDescriptionContextID),
        ("character.attribute", CharacterAttributeContextID),
        ("character.detail", CharacterDetailContextID),
        ("world_entry.manual", WorldEntryManualContextID),
        ("history_entry.static", StaticHistoryEntryContextID),
        ("history_entry.dynamic", DynamicHistoryEntryContextID),
    ],
)
def test_get_context_id_type(context_type, expected_class):
    """Test getting context ID type by string."""
    cls = get_context_id_type(context_type)
    assert cls == expected_class


@pytest.mark.parametrize(
    "context_type",
    [
        "character.description",
        "character.attribute",
        "character.detail",
        "world_entry.manual",
        "history_entry",
        "history_entry.static",
        "history_entry.dynamic",
    ],
)
def test_context_id_types_registration(context_type):
    """Test that context types are properly registered."""
    assert context_type in CONTEXT_ID_TYPES


def test_get_context_id_type_missing():
    """Test that getting non-existent context type raises KeyError."""
    with pytest.raises(KeyError):
        get_context_id_type("nonexistent.type")


@pytest.mark.parametrize(
    "context_type, object_input, expected_type, expected_attrs",
    [
        (
            "character.description",
            "TestChar",
            CharacterDescriptionContextID,
            {"character": "TestChar", "path": ["TestChar", "description"]},
        ),
        (
            "character.description",
            Character(name="RealChar"),
            CharacterDescriptionContextID,
            {"character": "RealChar", "path": ["RealChar", "description"]},
        ),
        (
            "world_entry.manual",
            "manual_entry_123",
            WorldEntryManualContextID,
            {
                "entry_id": "manual_entry_123",
                "path": [compress_name("manual_entry_123")],
            },
        ),
        (
            "world_entry.manual",
            ManualContext(id="ctx_456", text="test context"),
            WorldEntryManualContextID,
            {"entry_id": "ctx_456", "path": [compress_name("ctx_456")]},
        ),
        (
            "history_entry.static",
            HistoryEntry(text="test", ts="PT1S", index=0, layer=0, id="hist_123"),
            StaticHistoryEntryContextID,
            {"entry_id": "hist_123", "path": ["hist_123"]},
        ),
        (
            "history_entry.dynamic",
            HistoryEntry(text="test", ts="PT1S", index=0, layer=3, id="hist_456"),
            DynamicHistoryEntryContextID,
            {
                "entry_id": "hist_456",
                "layer": 3,
                "path": ["layer", "3", "id", "hist_456"],
            },
        ),
    ],
)
def test_context_id_from_object(
    context_type, object_input, expected_type, expected_attrs
):
    """Test creating context IDs from objects using context_id_from_object."""
    context_id = context_id_from_object(context_type, object_input)
    assert isinstance(context_id, expected_type)

    for attr, expected_value in expected_attrs.items():
        assert getattr(context_id, attr) == expected_value


@pytest.mark.parametrize(
    "context_type, object_input, kwargs, expected_type, expected_attrs",
    [
        (
            "character.attribute",
            "TestChar",
            {"attribute": "strength"},
            CharacterAttributeContextID,
            {
                "character": "TestChar",
                "attribute": "strength",
                "path": ["TestChar", compress_name("strength")],
            },
        ),
        (
            "character.attribute",
            Character(name="RealChar"),
            {"attribute": "intelligence"},
            CharacterAttributeContextID,
            {
                "character": "RealChar",
                "attribute": "intelligence",
                "path": ["RealChar", compress_name("intelligence")],
            },
        ),
        (
            "character.detail",
            "TestChar",
            {"detail": "appearance"},
            CharacterDetailContextID,
            {
                "character": "TestChar",
                "detail": "appearance",
                "path": ["TestChar", compress_name("appearance")],
            },
        ),
        (
            "character.detail",
            Character(name="RealChar"),
            {"detail": "personality"},
            CharacterDetailContextID,
            {
                "character": "RealChar",
                "detail": "personality",
                "path": ["RealChar", compress_name("personality")],
            },
        ),
    ],
)
def test_context_id_from_object_with_kwargs(
    context_type, object_input, kwargs, expected_type, expected_attrs
):
    """Test context_id_from_object with kwargs for context types that require multiple arguments."""
    context_id = context_id_from_object(context_type, object_input, **kwargs)
    assert isinstance(context_id, expected_type)

    for attr, expected_value in expected_attrs.items():
        assert getattr(context_id, attr) == expected_value


def test_context_id_from_object_comprehensive():
    """Test that context_id_from_object works for all registered context types."""
    # Test all single-argument context types
    char_desc = context_id_from_object("character.description", "TestChar")
    assert isinstance(char_desc, CharacterDescriptionContextID)

    manual_entry = context_id_from_object("world_entry.manual", "test_entry")
    assert isinstance(manual_entry, WorldEntryManualContextID)

    static_hist = context_id_from_object(
        "history_entry.static",
        HistoryEntry(text="test", ts="PT1S", index=0, layer=0, id="test_123"),
    )
    assert isinstance(static_hist, StaticHistoryEntryContextID)
    assert static_hist.path == ["test_123"]

    dynamic_hist = context_id_from_object(
        "history_entry.dynamic",
        HistoryEntry(text="test", ts="PT1S", index=0, layer=2, id="test_456"),
    )
    assert isinstance(dynamic_hist, DynamicHistoryEntryContextID)

    # Test multi-argument context types with kwargs
    char_attr = context_id_from_object(
        "character.attribute", "TestChar", attribute="strength"
    )
    assert isinstance(char_attr, CharacterAttributeContextID)
    assert char_attr.attribute == "strength"

    char_detail = context_id_from_object(
        "character.detail", "TestChar", detail="appearance"
    )
    assert isinstance(char_detail, CharacterDetailContextID)
    assert char_detail.detail == "appearance"


@pytest.mark.parametrize(
    "context_id, expected_str",
    [
        (ContextID(path=["test", "path"]), "context:test.path"),
        (
            CharacterDescriptionContextID(
                character="TestChar", path=["TestChar", "description"]
            ),
            "character.description:TestChar.description",
        ),
        (
            CharacterAttributeContextID(
                character="Player",
                attribute="strength",
                path=["Player", compress_name("strength")],
            ),
            f"character.attribute:Player.{compress_name('strength')}",
        ),
        (
            CharacterDetailContextID(
                character="Hero",
                detail="appearance",
                path=["Hero", compress_name("appearance")],
            ),
            f"character.detail:Hero.{compress_name('appearance')}",
        ),
        (
            WorldEntryContextID(entry_id="world_123", path=["world_123"]),
            "world_entry:world_123",
        ),
        (
            WorldEntryManualContextID(
                entry_id="manual_456", path=[compress_name("manual_456")]
            ),
            f"world_entry.manual:{compress_name('manual_456')}",
        ),
        (
            StaticHistoryEntryContextID(entry_id="hist_789", path=["hist_789"]),
            "history_entry.static:hist_789",
        ),
        (
            DynamicHistoryEntryContextID(
                entry_id="dyn_abc", layer=3, path=["layer", "3", "id", "dyn_abc"]
            ),
            "history_entry.dynamic:layer.3.id.dyn_abc",
        ),
    ],
)
def test_context_id_str_method(context_id, expected_str):
    """Test that __str__ method works correctly for all context ID types."""
    assert str(context_id) == expected_str
    # Also verify that it's consistent with id property
    assert str(context_id) == context_id.id
    assert str(context_id) == context_id.path_to_str


def test_context_id_string_formatting():
    """Test that context IDs work correctly in string formatting contexts."""
    context_id = CharacterDescriptionContextID(
        character="TestChar", path=["TestChar", "description"]
    )

    # Test f-string formatting
    formatted = f"Context: {context_id}"
    assert formatted == "Context: character.description:TestChar.description"

    # Test string concatenation
    concatenated = "Prefix-" + str(context_id) + "-Suffix"
    assert concatenated == "Prefix-character.description:TestChar.description-Suffix"

    # Test in collections that might call __str__
    context_list = [context_id]
    assert str(context_list[0]) == "character.description:TestChar.description"


def test_context_id_from_object_invalid_context_type():
    """Test context_id_from_object with invalid context type."""
    with pytest.raises(KeyError):
        context_id_from_object("nonexistent.type", "test_object")


# Tests for Character Context Handler and Context ID Value Flow


class MockScene:
    """Mock scene for testing context handlers."""

    def __init__(self):
        self.characters = {}

    def get_character(self, name: str) -> Character:
        return self.characters.get(name)

    def add_character(self, character: Character):
        self.characters[character.name] = character


@pytest.fixture
def mock_scene():
    """Create a mock scene with test characters."""
    scene = MockScene()

    # Create test character with attributes and details
    char = Character(
        name="TestCharacter",
        description="A brave warrior",
        base_attributes={"strength": 15, "intelligence": 12, "dexterity": 14},
        details={
            "appearance": "Tall and muscular",
            "personality": "Brave and loyal",
            "background": "Former knight",
        },
    )
    scene.add_character(char)

    # Create second character for testing
    char2 = Character(
        name="Wizard",
        description="A wise spellcaster",
        base_attributes={"intelligence": 18, "wisdom": 16},
        details={"appearance": "Old with a long beard", "specialty": "Fire magic"},
    )
    scene.add_character(char2)

    return scene


def test_character_context_handler_registration():
    """Test that CharacterContext handler is properly registered."""

    # Verify handler is registered for all expected context types
    expected_types = [
        "character.description",
        "character.attribute",
        "character.detail",
    ]

    for context_type in expected_types:
        assert context_type in CONTEXT_ID_PATH_HANDLERS
        assert CONTEXT_ID_PATH_HANDLERS[context_type] == CharacterContext


def test_character_context_instance_from_path(mock_scene):
    """Test CharacterContext.instance_from_path method."""

    # Test successful character lookup
    handler = CharacterContext.instance_from_path(["TestCharacter"], mock_scene)
    assert handler is not None
    assert handler.character.name == "TestCharacter"

    # Test with non-existent character should raise ContextIDHandlerError
    with pytest.raises(
        ContextIDHandlerError, match="Character 'NonExistent' not found in scene"
    ):
        CharacterContext.instance_from_path(["NonExistent"], mock_scene)


def test_character_context_properties(mock_scene):
    """Test CharacterContext property accessors."""

    handler = CharacterContext.instance_from_path(["TestCharacter"], mock_scene)

    # Test description property
    desc = handler.description
    assert desc.context_type == "description"
    assert desc.character.name == "TestCharacter"
    assert desc.name == "description"
    assert desc.value == "A brave warrior"

    # Test attributes generator
    attributes = list(handler.attributes)
    assert len(attributes) == 3
    attr_names = [attr.name for attr in attributes]
    assert "strength" in attr_names
    assert "intelligence" in attr_names
    assert "dexterity" in attr_names

    for attr in attributes:
        assert attr.context_type == "attribute"
        assert attr.character.name == "TestCharacter"

    # Test details generator
    details = list(handler.details)
    assert len(details) == 3
    detail_names = [detail.name for detail in details]
    assert "appearance" in detail_names
    assert "personality" in detail_names
    assert "background" in detail_names

    for detail in details:
        assert detail.context_type == "detail"
        assert detail.character.name == "TestCharacter"


def test_character_context_get_methods(mock_scene):
    """Test CharacterContext.get_attribute and get_detail methods."""

    handler = CharacterContext.instance_from_path(["TestCharacter"], mock_scene)

    # Test get_attribute
    strength = handler.get_attribute("strength")
    assert strength is not None
    assert strength.name == "strength"
    assert strength.value == 15

    # Test get_attribute for non-existent attribute
    missing = handler.get_attribute("charisma")
    assert missing is None

    # Test get_detail
    appearance = handler.get_detail("appearance")
    assert appearance is not None
    assert appearance.name == "appearance"
    assert appearance.value == "Tall and muscular"

    # Test get_detail for non-existent detail
    missing = handler.get_detail("missing_detail")
    assert missing is None


@pytest.mark.asyncio
async def test_character_context_item_operations(mock_scene):
    """Test CharacterContextItem get and set operations."""

    handler = CharacterContext.instance_from_path(["TestCharacter"], mock_scene)
    character = handler.character

    # Mock the memory agent since we don't have a real one in tests
    mock_memory_agent = AsyncMock()
    with patch("talemate.instance.get_agent", return_value=mock_memory_agent):
        # Test description operations
        desc_item = handler.description
        value = await desc_item.get(mock_scene)
        assert value == "A brave warrior"

        await desc_item.set(mock_scene, "Updated description")
        assert character.description == "Updated description"

        # Test attribute operations
        strength_item = handler.get_attribute("strength")
        value = await strength_item.get(mock_scene)
        assert value == 15

        await strength_item.set(mock_scene, 18)
        assert character.base_attributes["strength"] == 18

        # Test detail operations
        appearance_item = handler.get_detail("appearance")
        value = await appearance_item.get(mock_scene)
        assert value == "Tall and muscular"

        await appearance_item.set(mock_scene, "Short and thin")
        assert character.details["appearance"] == "Short and thin"


def test_character_context_item_context_id_property(mock_scene):
    """Test that CharacterContextItem.context_id returns correct ContextID types."""

    handler = CharacterContext.instance_from_path(["TestCharacter"], mock_scene)

    # Test description context_id
    desc_item = handler.description
    context_id = desc_item.context_id
    assert isinstance(context_id, CharacterDescriptionContextID)
    assert context_id.character == "TestCharacter"

    # Test attribute context_id
    strength_item = handler.get_attribute("strength")
    context_id = strength_item.context_id
    assert isinstance(context_id, CharacterAttributeContextID)
    assert context_id.character == "TestCharacter"
    assert context_id.attribute == "strength"

    # Test detail context_id
    appearance_item = handler.get_detail("appearance")
    context_id = appearance_item.context_id
    assert isinstance(context_id, CharacterDetailContextID)
    assert context_id.character == "TestCharacter"
    assert context_id.detail == "appearance"


def test_character_context_item_human_id_property(mock_scene):
    """Test that CharacterContextItem.human_id returns human-readable descriptions."""

    handler = CharacterContext.instance_from_path(["TestCharacter"], mock_scene)

    # Test description human_id
    desc_item = handler.description
    assert desc_item.human_id == "Information about TestCharacter - 'description'"

    # Test attribute human_id
    strength_item = handler.get_attribute("strength")
    assert strength_item.human_id == "Information about TestCharacter - 'strength'"

    # Test detail human_id
    appearance_item = handler.get_detail("appearance")
    assert appearance_item.human_id == "Information about TestCharacter - 'appearance'"


def test_character_context_compressed_path(mock_scene):
    """Test that CharacterContextItem.compressed_path returns correct path strings."""

    handler = CharacterContext.instance_from_path(["TestCharacter"], mock_scene)

    # Test description compressed path
    desc_item = handler.description
    assert (
        desc_item.compressed_path == "character.description:TestCharacter.description"
    )

    # Test attribute compressed path
    strength_item = handler.get_attribute("strength")
    expected_path = f"character.attribute:TestCharacter.{compress_name('strength')}"
    assert strength_item.compressed_path == expected_path

    # Test detail compressed path
    appearance_item = handler.get_detail("appearance")
    expected_path = f"character.detail:TestCharacter.{compress_name('appearance')}"
    assert appearance_item.compressed_path == expected_path


@pytest.mark.asyncio
async def test_character_context_id_item_from_path(mock_scene):
    """Test CharacterContext.context_id_item_from_path method."""

    # Create handler instance first
    handler = CharacterContext.instance_from_path(["TestCharacter"], mock_scene)

    # Test description context
    desc_value = await handler.context_id_item_from_path(
        "character.description",
        ["TestCharacter", "description"],
        "character.description:TestCharacter.description",
        mock_scene,
    )
    assert desc_value is not None
    assert desc_value.context_type == "description"
    assert desc_value.character.name == "TestCharacter"

    # Test attribute context
    strength_compressed = compress_name("strength")
    attr_path_str = f"character.attribute:TestCharacter.{strength_compressed}"
    attr_value = await handler.context_id_item_from_path(
        "character.attribute",
        ["TestCharacter", strength_compressed],
        attr_path_str,
        mock_scene,
    )
    assert attr_value is not None
    assert attr_value.context_type == "attribute"
    assert attr_value.name == "strength"
    assert attr_value.value == 15

    # Test detail context
    appearance_compressed = compress_name("appearance")
    detail_path_str = f"character.detail:TestCharacter.{appearance_compressed}"
    detail_value = await handler.context_id_item_from_path(
        "character.detail",
        ["TestCharacter", appearance_compressed],
        detail_path_str,
        mock_scene,
    )
    assert detail_value is not None
    assert detail_value.context_type == "detail"
    assert detail_value.name == "appearance"
    assert detail_value.value == "Tall and muscular"

    # Test non-existent character should raise ContextIDHandlerError

    with pytest.raises(
        ContextIDHandlerError, match="Character 'NonExistent' not found in scene"
    ):
        non_existent_handler = CharacterContext.instance_from_path(
            ["NonExistent"], mock_scene
        )
        await non_existent_handler.context_id_item_from_path(
            "character.description",
            ["NonExistent", "description"],
            "character.description:NonExistent.description",
            mock_scene,
        )

    # Test invalid context type
    none_value = await handler.context_id_item_from_path(
        "invalid.type",
        ["TestCharacter", "description"],
        "invalid.type:TestCharacter.description",
        mock_scene,
    )
    assert none_value is None


@pytest.mark.asyncio
async def test_character_context_id_from_path(mock_scene):
    """Test CharacterContext.context_id_from_path method."""

    # Test description context ID
    handler = CharacterContext.instance_from_path(["TestCharacter"], mock_scene)
    desc_context_id = await handler.context_id_from_path(
        "character.description",
        ["TestCharacter", "description"],
        "character.description:TestCharacter.description",
        mock_scene,
    )
    assert desc_context_id is not None
    assert isinstance(desc_context_id, CharacterDescriptionContextID)
    assert desc_context_id.character == "TestCharacter"

    # Test attribute context ID
    strength_compressed = compress_name("strength")
    attr_path_str = f"character.attribute:TestCharacter.{strength_compressed}"
    attr_context_id = await handler.context_id_from_path(
        "character.attribute",
        ["TestCharacter", strength_compressed],
        attr_path_str,
        mock_scene,
    )
    assert attr_context_id is not None
    assert isinstance(attr_context_id, CharacterAttributeContextID)
    assert attr_context_id.character == "TestCharacter"
    assert attr_context_id.attribute == "strength"

    # Test detail context ID
    appearance_compressed = compress_name("appearance")
    detail_path_str = f"character.detail:TestCharacter.{appearance_compressed}"
    detail_context_id = await handler.context_id_from_path(
        "character.detail",
        ["TestCharacter", appearance_compressed],
        detail_path_str,
        mock_scene,
    )
    assert detail_context_id is not None
    assert isinstance(detail_context_id, CharacterDetailContextID)
    assert detail_context_id.character == "TestCharacter"
    assert detail_context_id.detail == "appearance"

    # Test non-existent character should raise ContextIDHandlerError
    with pytest.raises(
        ContextIDHandlerError, match="Character 'NonExistent' not found in scene"
    ):
        non_existent_handler = CharacterContext.instance_from_path(
            ["NonExistent"], mock_scene
        )
        await non_existent_handler.context_id_from_path(
            "character.description",
            ["NonExistent", "description"],
            "character.description:NonExistent.description",
            mock_scene,
        )


def test_context_id_handler_lookup(mock_scene):
    """Test context_id_handler_from_string function."""

    # Test valid character context types
    for context_type in [
        "character.description",
        "character.attribute",
        "character.detail",
    ]:
        context_id_str = f"{context_type}:TestCharacter.test"
        handler = context_id_handler_from_string(context_id_str, mock_scene)
        assert isinstance(handler, CharacterContext)

    # Test invalid context type
    with pytest.raises(ContextIDNoHandlerFound):
        context_id_handler_from_string("nonexistent.type:test.path", mock_scene)


@pytest.mark.asyncio
async def test_integration_context_id_item_flow(mock_scene):
    """Test the complete context ID value flow from string to value operations."""

    # Test functions directly with mock_scene parameter

    # Test description flow
    desc_context_id_str = "character.description:TestCharacter.description"

    # Test context_id_item_from_string
    context_value = await context_id_item_from_string(desc_context_id_str, mock_scene)
    assert context_value is not None
    assert context_value.context_type == "description"
    assert context_value.character.name == "TestCharacter"
    assert context_value.value == "A brave warrior"

    # Test context_id_from_string
    context_id = await context_id_from_string(desc_context_id_str, mock_scene)
    assert context_id is not None
    assert isinstance(context_id, CharacterDescriptionContextID)
    assert context_id.character == "TestCharacter"

    # Test attribute flow
    strength_compressed = compress_name("strength")
    attr_context_id_str = f"character.attribute:TestCharacter.{strength_compressed}"

    context_value = await context_id_item_from_string(attr_context_id_str, mock_scene)
    assert context_value is not None
    assert context_value.context_type == "attribute"
    assert context_value.name == "strength"
    assert context_value.value == 15

    context_id = await context_id_from_string(attr_context_id_str, mock_scene)
    assert context_id is not None
    assert isinstance(context_id, CharacterAttributeContextID)
    assert context_id.attribute == "strength"

    # Test detail flow
    appearance_compressed = compress_name("appearance")
    detail_context_id_str = f"character.detail:TestCharacter.{appearance_compressed}"

    context_value = await context_id_item_from_string(detail_context_id_str, mock_scene)
    assert context_value is not None
    assert context_value.context_type == "detail"
    assert context_value.name == "appearance"
    assert context_value.value == "Tall and muscular"

    context_id = await context_id_from_string(detail_context_id_str, mock_scene)
    assert context_id is not None
    assert isinstance(context_id, CharacterDetailContextID)
    assert context_id.detail == "appearance"


@pytest.mark.asyncio
async def test_integration_context_id_item_flow_no_scene():
    """Test context ID value flow when no active scene is available."""

    # Create empty scene with no characters
    empty_scene = MockScene()

    desc_context_id_str = "character.description:TestCharacter.description"

    # Should raise ContextIDHandlerError when character not found
    with pytest.raises(
        ContextIDHandlerError, match="Character 'TestCharacter' not found in scene"
    ):
        await context_id_item_from_string(desc_context_id_str, empty_scene)

    with pytest.raises(
        ContextIDHandlerError, match="Character 'TestCharacter' not found in scene"
    ):
        await context_id_from_string(desc_context_id_str, empty_scene)


@pytest.mark.asyncio
async def test_integration_context_id_item_flow_nonexistent_character(mock_scene):
    """Test context ID value flow with nonexistent character."""

    # Test with nonexistent character should raise ContextIDHandlerError
    desc_context_id_str = "character.description:NonExistent.description"

    with pytest.raises(
        ContextIDHandlerError, match="Character 'NonExistent' not found in scene"
    ):
        await context_id_item_from_string(desc_context_id_str, mock_scene)

    with pytest.raises(
        ContextIDHandlerError, match="Character 'NonExistent' not found in scene"
    ):
        await context_id_from_string(desc_context_id_str, mock_scene)


@pytest.mark.asyncio
async def test_integration_full_context_value_operations(mock_scene):
    """Test full integration of context value operations through the context ID system."""

    # Mock memory agent
    mock_memory_agent = AsyncMock()
    with patch("talemate.instance.get_agent", return_value=mock_memory_agent):
        # Get context value for character description
        desc_context_id_str = "character.description:TestCharacter.description"
        context_value = await context_id_item_from_string(
            desc_context_id_str, mock_scene
        )
        assert context_value is not None

        # Test get operation
        original_value = await context_value.get(mock_scene)
        assert original_value == "A brave warrior"

        # Test set operation
        await context_value.set(mock_scene, "A legendary warrior")
        updated_value = await context_value.get(mock_scene)
        assert updated_value == "A legendary warrior"

        # Verify character was actually updated
        character = mock_scene.get_character("TestCharacter")
        assert character.description == "A legendary warrior"

        # Test attribute operations
        strength_compressed = compress_name("strength")
        attr_context_id_str = f"character.attribute:TestCharacter.{strength_compressed}"
        attr_context_value = await context_id_item_from_string(
            attr_context_id_str, mock_scene
        )
        assert attr_context_value is not None

        original_strength = await attr_context_value.get(mock_scene)
        assert original_strength == 15

        await attr_context_value.set(mock_scene, 20)
        updated_strength = await attr_context_value.get(mock_scene)
        assert updated_strength == 20
        assert character.base_attributes["strength"] == 20

        # Test detail operations
        appearance_compressed = compress_name("appearance")
        detail_context_id_str = (
            f"character.detail:TestCharacter.{appearance_compressed}"
        )
        detail_context_value = await context_id_item_from_string(
            detail_context_id_str, mock_scene
        )
        assert detail_context_value is not None

        original_appearance = await detail_context_value.get(mock_scene)
        assert original_appearance == "Tall and muscular"

        await detail_context_value.set(mock_scene, "Imposing and battle-scarred")
        updated_appearance = await detail_context_value.get(mock_scene)
        assert updated_appearance == "Imposing and battle-scarred"
        assert character.details["appearance"] == "Imposing and battle-scarred"


def test_character_context_edge_cases(mock_scene):
    """Test edge cases for character context operations."""

    # Test with empty character name should raise ContextIDHandlerError
    with pytest.raises(ContextIDHandlerError, match="Character '' not found in scene"):
        CharacterContext.instance_from_path([""], mock_scene)

    # Test with character that has no attributes or details
    empty_char = Character(name="EmptyChar", description="Empty character")
    mock_scene.add_character(empty_char)

    handler = CharacterContext.instance_from_path(["EmptyChar"], mock_scene)
    assert handler is not None

    # Should return empty lists for attributes and details
    attributes = list(handler.attributes)
    details = list(handler.details)
    assert len(attributes) == 0
    assert len(details) == 0

    # Description should still work
    desc_item = handler.description
    assert desc_item.value == "Empty character"

    # get_attribute and get_detail should return None for non-existent items
    assert handler.get_attribute("nonexistent") is None
    assert handler.get_detail("nonexistent") is None


# Tests for Story Configuration Context IDs


class MockSceneIntent:
    """Mock scene intent for testing story configuration context handlers."""

    def __init__(self):
        self.intent = "Overall story intention"
        self.instructions = "Director instructions for managing the scene"
        self.phase = None
        self.scene_types = {}


class MockSceneForStoryConfig:
    """Mock scene for testing story configuration context handlers."""

    def __init__(self):
        self.title = "Test Story"
        self.name = "test_story"
        self.description = "A test story description"
        self.context = "Adult themes, fantasy setting"
        self.intent_state = MockSceneIntent()
        self.characters = {}

    def get_intro(self):
        return "This is the story introduction."

    def set_intro(self, value):
        self._intro = value

    def emit_scene_intent(self):
        """Mock emit method."""
        pass


@pytest.fixture
def mock_scene_story_config():
    """Create a mock scene for testing story configuration context IDs."""
    return MockSceneForStoryConfig()


def test_director_instructions_context_id_creation():
    """Test DirectorInstructionsContextID creation."""
    context_id = DirectorInstructionsContextID.make()
    assert context_id.key == "director_instructions"
    assert context_id.path == ["director_instructions"]
    assert context_id.context_type == "story_configuration"
    assert context_id.path_to_str == "story_configuration:director_instructions"


def test_director_instructions_context_id_properties():
    """Test DirectorInstructionsContextID properties."""
    context_id = DirectorInstructionsContextID.make()
    assert str(context_id) == "story_configuration:director_instructions"
    assert context_id.id == "story_configuration:director_instructions"
    assert "director" in context_id.context_type_label.lower()


def test_story_configuration_context_handler_registration():
    """Test that StoryConfigurationContext handler is properly registered."""
    assert "story_configuration" in CONTEXT_ID_PATH_HANDLERS
    assert CONTEXT_ID_PATH_HANDLERS["story_configuration"] == StoryConfigurationContext


@pytest.mark.asyncio
async def test_director_instructions_context_item_get(mock_scene_story_config):
    """Test getting director instructions through context item."""
    handler = StoryConfigurationContext.instance_from_path(
        ["director_instructions"], mock_scene_story_config
    )
    assert handler is not None

    item = await handler.context_id_item_from_path(
        "story_configuration",
        ["director_instructions"],
        "story_configuration:director_instructions",
        mock_scene_story_config,
    )

    assert item is not None
    assert item.context_type == "director_instructions"
    assert item.name == "director_instructions"
    assert item.value == "Director instructions for managing the scene"

    # Test get method
    value = await item.get(mock_scene_story_config)
    assert value == "Director instructions for managing the scene"


@pytest.mark.asyncio
async def test_director_instructions_context_item_set(mock_scene_story_config):
    """Test setting director instructions through context item."""
    handler = StoryConfigurationContext.instance_from_path(
        ["director_instructions"], mock_scene_story_config
    )

    item = await handler.context_id_item_from_path(
        "story_configuration",
        ["director_instructions"],
        "story_configuration:director_instructions",
        mock_scene_story_config,
    )

    # Test set method
    new_instructions = "Updated director instructions"
    await item.set(mock_scene_story_config, new_instructions)
    assert mock_scene_story_config.intent_state.instructions == new_instructions

    # Test setting to None
    await item.set(mock_scene_story_config, None)
    assert mock_scene_story_config.intent_state.instructions is None

    # Test setting empty string converts to None
    await item.set(mock_scene_story_config, "")
    assert mock_scene_story_config.intent_state.instructions is None


@pytest.mark.asyncio
async def test_director_instructions_context_id_from_path(mock_scene_story_config):
    """Test getting DirectorInstructionsContextID from path."""
    handler = StoryConfigurationContext.instance_from_path(
        ["director_instructions"], mock_scene_story_config
    )

    context_id = await handler.context_id_from_path(
        "story_configuration",
        ["director_instructions"],
        "story_configuration:director_instructions",
        mock_scene_story_config,
    )

    assert context_id is not None
    assert isinstance(context_id, DirectorInstructionsContextID)
    assert context_id.path == ["director_instructions"]


def test_director_instructions_context_item_properties(mock_scene_story_config):
    """Test DirectorInstructionsContextItem properties."""
    item = StoryConfigurationContextItem(
        context_type="director_instructions",
        name="director_instructions",
        value="Test instructions",
    )

    # Test context_id property
    context_id = item.context_id
    assert isinstance(context_id, DirectorInstructionsContextID)

    # Test human_id property
    assert item.human_id == "Director Instructions"


@pytest.mark.asyncio
async def test_director_instructions_integration_flow(mock_scene_story_config):
    """Test complete integration flow for director instructions context ID."""
    context_id_str = "story_configuration:director_instructions"

    # Test context_id_item_from_string
    context_item = await context_id_item_from_string(
        context_id_str, mock_scene_story_config
    )
    assert context_item is not None
    assert context_item.context_type == "director_instructions"
    assert context_item.value == "Director instructions for managing the scene"

    # Test context_id_from_string
    context_id = await context_id_from_string(context_id_str, mock_scene_story_config)
    assert context_id is not None
    assert isinstance(context_id, DirectorInstructionsContextID)

    # Test get and set operations
    original_value = await context_item.get(mock_scene_story_config)
    assert original_value == "Director instructions for managing the scene"

    new_value = "New instructions for the director"
    await context_item.set(mock_scene_story_config, new_value)

    updated_value = await context_item.get(mock_scene_story_config)
    assert updated_value == new_value
    assert mock_scene_story_config.intent_state.instructions == new_value


@pytest.mark.asyncio
async def test_director_instructions_with_none_value(mock_scene_story_config):
    """Test director instructions context ID when instructions are None."""
    mock_scene_story_config.intent_state.instructions = None

    context_id_str = "story_configuration:director_instructions"
    context_item = await context_id_item_from_string(
        context_id_str, mock_scene_story_config
    )

    assert context_item is not None
    value = await context_item.get(mock_scene_story_config)
    assert value is None
