from talemate.load.character_card import (
    create_manual_context_from_character_book,
    CharacterBook,
    CharacterBookEntry,
)
from talemate.world_state import ManualContext


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_create_manual_context_from_character_book_none():
    """Test that None character_book returns empty dict."""
    result = create_manual_context_from_character_book(None)
    assert result == {}


def test_create_manual_context_from_character_book_empty():
    """Test that empty character_book returns empty dict."""
    character_book = CharacterBook(entries=[])
    result = create_manual_context_from_character_book(character_book)
    assert result == {}


def test_create_manual_context_from_character_book_single_entry():
    """Test creating ManualContext from a single character book entry."""
    entry = CharacterBookEntry(
        keys=["Alice", "Character"],
        content="Alice is a friendly character.",
        enabled=True,
        id=1,
    )
    character_book = CharacterBook(
        name="Test Book",
        entries=[entry],
    )

    result = create_manual_context_from_character_book(character_book)

    assert len(result) == 1
    entry_id = "character_book_1"
    assert entry_id in result

    manual_context = result[entry_id]
    assert isinstance(manual_context, ManualContext)
    assert manual_context.id == entry_id
    assert manual_context.text == "Alice is a friendly character."
    assert manual_context.meta["source"] == "imported"
    assert "chara" in manual_context.meta
    assert manual_context.meta["chara"]["character_book_name"] == "Test Book"
    assert manual_context.meta["chara"]["keys"] == ["Alice", "Character"]
    assert manual_context.shared is False


def test_create_manual_context_from_character_book_multiple_entries():
    """Test creating ManualContext from multiple character book entries."""
    entries = [
        CharacterBookEntry(
            keys=["Alice"],
            content="Alice is a character.",
            enabled=True,
            id=1,
        ),
        CharacterBookEntry(
            keys=["Bob"],
            content="Bob is another character.",
            enabled=True,
            id=2,
        ),
    ]
    character_book = CharacterBook(
        name="Multi Entry Book",
        entries=entries,
    )

    result = create_manual_context_from_character_book(character_book)

    assert len(result) == 2
    assert "character_book_1" in result
    assert "character_book_2" in result

    assert result["character_book_1"].text == "Alice is a character."
    assert result["character_book_2"].text == "Bob is another character."


def test_create_manual_context_from_character_book_disabled_entry():
    """Test that disabled entries are skipped by default."""
    entries = [
        CharacterBookEntry(
            keys=["Alice"],
            content="Alice is enabled.",
            enabled=True,
            id=1,
        ),
        CharacterBookEntry(
            keys=["Bob"],
            content="Bob is disabled.",
            enabled=False,
            id=2,
        ),
    ]
    character_book = CharacterBook(entries=entries)

    result = create_manual_context_from_character_book(character_book)

    assert len(result) == 1
    assert "character_book_1" in result
    assert "character_book_2" not in result


def test_create_manual_context_from_character_book_include_disabled():
    """Test that disabled entries can be included when skip_disabled=False."""
    entries = [
        CharacterBookEntry(
            keys=["Alice"],
            content="Alice is enabled.",
            enabled=True,
            id=1,
        ),
        CharacterBookEntry(
            keys=["Bob"],
            content="Bob is disabled.",
            enabled=False,
            id=2,
        ),
    ]
    character_book = CharacterBook(entries=entries)

    result = create_manual_context_from_character_book(
        character_book, skip_disabled=False
    )

    assert len(result) == 2
    assert "character_book_1" in result
    assert "character_book_2" in result


def test_create_manual_context_from_character_book_with_optional_fields():
    """Test creating ManualContext with optional fields populated."""
    entry = CharacterBookEntry(
        keys=["Alice"],
        content="Alice content",
        enabled=True,
        id=1,
        name="Alice Entry",
        priority=10,
        selective=True,
        secondary_keys=["secondary1", "secondary2"],
        constant=True,
        position="before_char",
        insertion_order=5,
        case_sensitive=True,
    )
    character_book = CharacterBook(
        name="Optional Fields Book",
        entries=[entry],
    )

    result = create_manual_context_from_character_book(character_book)

    assert len(result) == 1
    # Entry name should be used as ID when set
    manual_context = result["Alice Entry"]
    assert manual_context.id == "Alice Entry"
    meta = manual_context.meta
    chara = meta["chara"]

    assert chara["entry_name"] == "Alice Entry"
    assert chara["priority"] == 10
    assert chara["selective"] is True
    assert chara["secondary_keys"] == ["secondary1", "secondary2"]
    assert chara["constant"] is True
    assert chara["position"] == "before_char"
    assert chara["insertion_order"] == 5
    assert chara["case_sensitive"] is True


def test_create_manual_context_from_character_book_with_extensions():
    """Test that extensions are included in chara metadata."""
    entry = CharacterBookEntry(
        keys=["Alice"],
        content="Alice content",
        enabled=True,
        id=1,
        extensions={"custom_field": "custom_value", "depth": 4},
    )
    character_book = CharacterBook(
        name="Extensions Book",
        entries=[entry],
        extensions={"book_extension": "book_value"},
    )

    result = create_manual_context_from_character_book(character_book)

    assert len(result) == 1
    manual_context = result["character_book_1"]
    assert "extensions" in manual_context.meta["chara"]
    assert manual_context.meta["chara"]["extensions"]["custom_field"] == "custom_value"
    assert manual_context.meta["chara"]["extensions"]["depth"] == 4


def test_create_manual_context_from_character_book_without_id():
    """Test that entries without id get UUID-based IDs."""
    entry = CharacterBookEntry(
        keys=["Alice", "Character"],
        content="Alice is a character.",
        enabled=True,
        # No id provided
    )
    character_book = CharacterBook(entries=[entry])

    result = create_manual_context_from_character_book(character_book)

    assert len(result) == 1
    # Should have a generated UUID-based ID
    entry_id = list(result.keys())[0]
    assert entry_id.startswith("character_book_")
    # UUID hex is 10 chars after the prefix
    assert len(entry_id) == len("character_book_") + 10


def test_create_manual_context_from_character_book_dict_input():
    """Test that dict input is converted to CharacterBook."""
    character_book_dict = {
        "name": "Dict Book",
        "entries": [
            {
                "keys": ["Alice"],
                "content": "Alice from dict.",
                "enabled": True,
                "id": 1,
            }
        ],
    }

    result = create_manual_context_from_character_book(character_book_dict)

    assert len(result) == 1
    assert "character_book_1" in result
    assert result["character_book_1"].text == "Alice from dict."
    assert (
        result["character_book_1"].meta["chara"]["character_book_name"] == "Dict Book"
    )


def test_create_manual_context_from_character_book_invalid_dict():
    """Test that invalid dict input returns empty dict."""
    invalid_dict = {
        "name": "Invalid",
        "entries": [
            {
                # Missing required 'keys' field
                "content": "Invalid entry.",
            }
        ],
    }

    result = create_manual_context_from_character_book(invalid_dict)

    # Should return empty dict due to validation error
    assert result == {}


def test_create_manual_context_from_character_book_no_book_name():
    """Test handling of missing book name."""
    entry = CharacterBookEntry(
        keys=["Alice"],
        content="Alice content",
        enabled=True,
        id=1,
    )
    character_book = CharacterBook(entries=[entry])  # No name

    result = create_manual_context_from_character_book(character_book)

    assert len(result) == 1
    assert result["character_book_1"].meta["chara"]["character_book_name"] == ""


def test_create_manual_context_from_character_book_without_meta():
    """Test that chara metadata is not included when import_meta=False."""
    entry = CharacterBookEntry(
        keys=["Alice"],
        content="Alice content",
        enabled=True,
        id=1,
        priority=10,
    )
    character_book = CharacterBook(
        name="Test Book",
        entries=[entry],
    )

    result = create_manual_context_from_character_book(
        character_book, import_meta=False
    )

    assert len(result) == 1
    manual_context = result["character_book_1"]
    assert manual_context.meta["source"] == "imported"
    assert "chara" not in manual_context.meta
