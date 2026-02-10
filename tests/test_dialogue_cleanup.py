import pytest
from talemate.util import ensure_dialog_format, clean_dialogue, remove_trailing_markers

MULTILINE_TEST_A_INPUT = """
\"The first line.

The second line.

- list item
- list item

The third line.\"
"""
MULTILINE_TEST_A_EXPECTED = """
\"The first line.

The second line.

- list item
- list item

The third line.\"
"""


@pytest.mark.parametrize(
    "input, expected",
    [
        ("Hello how are you?", "Hello how are you?"),
        ('"Hello how are you?"', '"Hello how are you?"'),
        (
            '"Hello how are you?" he asks "I am fine"',
            '"Hello how are you?" *he asks* "I am fine"',
        ),
        (
            "Hello how are you? *he asks* I am fine",
            '"Hello how are you?" *he asks* "I am fine"',
        ),
        (
            'Hello how are you?" *he asks* I am fine',
            '"Hello how are you?" *he asks* "I am fine"',
        ),
        (
            'Hello how are you?" *he asks I am fine',
            '"Hello how are you?" *he asks I am fine*',
        ),
        (
            'Hello how are you?" *he asks* "I am fine" *',
            '"Hello how are you?" *he asks* "I am fine"',
        ),
        (
            '"Hello how are you *he asks* I am fine"',
            '"Hello how are you" *he asks* "I am fine"',
        ),
        (
            "This is a string without any markers",
            "This is a string without any markers",
        ),
        (
            'This is a string with an ending quote"',
            '"This is a string with an ending quote"',
        ),
        (
            "This is a string with an ending asterisk*",
            "*This is a string with an ending asterisk*",
        ),
        ('"Mixed markers*', "*Mixed markers*"),
        (
            '*narrative.* dialogue" *more narrative.*',
            '*narrative.* "dialogue" *more narrative.*',
        ),
        (
            '"*messed up dialogue formatting.*" *some narration.*',
            '"messed up dialogue formatting." *some narration.*',
        ),
        (
            '*"messed up narration formatting."* "some dialogue."',
            '"messed up narration formatting." "some dialogue."',
        ),
        (
            "Some dialogue and two line-breaks right after, followed by narration.\n\n*Narration*",
            '"Some dialogue and two line-breaks right after, followed by narration."\n\n*Narration*',
        ),
        (
            '*Some narration with a "quoted" string in it.* Then some unquoted dialogue.\n\n*More narration.*',
            '*Some narration with a* "quoted" *string in it.* "Then some unquoted dialogue."\n\n*More narration.*',
        ),
        (
            "*Some narration* Some dialogue but not in quotes. *",
            '*Some narration* "Some dialogue but not in quotes."',
        ),
        (
            "*First line\nSecond line\nThird line*",
            "*First line\nSecond line\nThird line*",
        ),
        (MULTILINE_TEST_A_INPUT, MULTILINE_TEST_A_EXPECTED),
    ],
)
def test_dialogue_cleanup(input, expected):
    assert ensure_dialog_format(input) == expected


@pytest.mark.parametrize(
    "input, expected, main_name",
    [
        ("bob: says a sentence", "bob: says a sentence", "bob"),
        (
            "bob: says a sentence\nbob: says another sentence",
            "bob: says a sentence\nsays another sentence",
            "bob",
        ),
        (
            "bob: says a sentence with a colon: to explain something",
            "bob: says a sentence with a colon: to explain something",
            "bob",
        ),
        (
            "bob: i have a riddle for you, alice: the riddle",
            "bob: i have a riddle for you, alice: the riddle",
            "bob",
        ),
        # without other_names, lines with colons are kept (safe fallback)
        (
            "bob: says something\nalice: says something else",
            "bob: says something\nalice: says something else",
            "bob",
        ),
        ("bob: says a sentence. then a", "bob: says a sentence.", "bob"),
        (
            "bob: first paragraph\n\nsecond paragraph",
            "bob: first paragraph\n\nsecond paragraph",
            "bob",
        ),
        # movie script new speaker cutoff (all-caps still caught)
        (
            "bob: says a sentence\n\nALICE\nsays something else",
            "bob: says a sentence",
            "bob",
        ),
        # narrative colon in mid-paragraph preserved
        (
            "bob: first paragraph\n\nShe reported back: the details were clear.",
            "bob: first paragraph\n\nShe reported back: the details were clear.",
            "bob",
        ),
        # time notation with colon preserved
        (
            "bob: woke up early\n\nThe clock read 3:45 AM.",
            "bob: woke up early\n\nThe clock read 3:45 AM.",
            "bob",
        ),
        # parenthetical with colon preserved
        (
            "bob: did something\n\n(Note: this was important.)",
            "bob: did something\n\n(Note: this was important.)",
            "bob",
        ),
    ],
)
def test_clean_dialogue(input, expected, main_name):
    assert clean_dialogue(input, main_name) == expected


@pytest.mark.parametrize(
    "input, expected, main_name, other_names",
    [
        # colons in prose are preserved when other_names is provided
        (
            "bob: The clock read 2:23 AM.",
            "bob: The clock read 2:23 AM.",
            "bob",
            ["alice"],
        ),
        # multi-paragraph with colons in prose
        (
            "bob: first paragraph\n\nThe time was 2:23 AM.\n\nThird paragraph.",
            "bob: first paragraph\n\nThe time was 2:23 AM.\n\nThird paragraph.",
            "bob",
            ["alice"],
        ),
        # still breaks on known other character speaking
        (
            "bob: says something\nalice: says something else",
            "bob: says something",
            "bob",
            ["alice"],
        ),
        # still breaks on other character without space after colon
        (
            "bob: says something\nalice:says something else",
            "bob: says something",
            "bob",
            ["alice"],
        ),
        # other character mid-text colon does NOT cause break
        (
            "bob: i have a riddle for you, alice: the riddle",
            "bob: i have a riddle for you, alice: the riddle",
            "bob",
            ["alice"],
        ),
        # movie script all-caps still breaks
        (
            "bob: says a sentence\n\nALICE\nsays something else",
            "bob: says a sentence",
            "bob",
            ["alice"],
        ),
        # narrative colon preserved while other speaker is dropped
        (
            "bob: first line\n\nShe reported back: the details were clear.\n\nalice: goodbye",
            "bob: first line\n\nShe reported back: the details were clear.",
            "bob",
            ["alice"],
        ),
        # multi-paragraph: narrative colons kept, other speaker mid-text dropped
        (
            "bob: woke up early\n\nThe clock read 3:45 AM.\n\nalice: good morning",
            "bob: woke up early\n\nThe clock read 3:45 AM.",
            "bob",
            ["alice"],
        ),
        # multiple other speakers, all dropped
        (
            "bob: says something\nalice: hello\ncharlie: hey",
            "bob: says something",
            "bob",
            ["alice", "charlie"],
        ),
        # other speaker on new paragraph boundary
        (
            "bob: first paragraph\n\nsecond paragraph\n\nalice: third paragraph",
            "bob: first paragraph\n\nsecond paragraph",
            "bob",
            ["alice"],
        ),
        # empty other_names list — colons preserved, no other speakers
        (
            "bob: The time was 3:00 PM.\n\nNext paragraph with note: important.",
            "bob: The time was 3:00 PM.\n\nNext paragraph with note: important.",
            "bob",
            [],
        ),
    ],
)
def test_clean_dialogue_with_other_names(input, expected, main_name, other_names):
    assert clean_dialogue(input, main_name, other_names=other_names) == expected


@pytest.mark.parametrize(
    "input, expected",
    [
        ('Hello how are you? "', "Hello how are you?"),
        ("Hello how are you? *", "Hello how are you?"),
        ("Hello how are you? {", "Hello how are you?"),
        ("Hello how are you? [", "Hello how are you?"),
        ("Hello how are you? (", "Hello how are you?"),
        ('"Hello how are you?"', '"Hello how are you?"'),
        ('"Hello how are you?" "', '"Hello how are you?"'),
        ('"Hello how are you?" *', '"Hello how are you?"'),
        ('"Hello how are you?" *"', '"Hello how are you?"'),
        ('*He says* "Hello how are you?"', '*He says* "Hello how are you?"'),
        ('*He says* "Hello how are you?" *', '*He says* "Hello how are you?"'),
        ('*He says* "Hello how are you?" *"', '*He says* "Hello how are you?"'),
        ("(Some thoughts)", "(Some thoughts)"),
        ("(Some thoughts) ", "(Some thoughts)"),
        ("(Some thoughts) (", "(Some thoughts)"),
        ("(Some thoughts) [", "(Some thoughts)"),
    ],
)
def test_remove_trailing_markers(input, expected):
    assert remove_trailing_markers(input) == expected


@pytest.mark.parametrize(
    "input, anchor_length, expected_non_anchor, expected_anchor",
    [
        ("", 10, "", ""),
        ("Hello", 10, "", "Hello"),
        ("This is a short example", 10, "This is", "a short example"),
        ("One two three four", 4, "One two", "three four"),
        (
            "This is a longer example with more than ten words to test the anchor functionality",
            10,
            "This is a longer example",
            "with more than ten words to test the anchor functionality",
        ),
        (
            "One two three four five six seven eight nine ten",
            10,
            "One two three four five",
            "six seven eight nine ten",
        ),
        ("Two words", 10, "Two", "words"),
        ("One Two Three", 3, "One", "Two Three"),
    ],
)
def test_split_anchor_text(input, anchor_length, expected_non_anchor, expected_anchor):
    from talemate.util.dialogue import split_anchor_text

    non_anchor, anchor = split_anchor_text(input, anchor_length)
    assert non_anchor == expected_non_anchor
    assert anchor == expected_anchor


@pytest.mark.parametrize(
    "input, expected",
    [
        # Empty text
        ("", []),
        # Only dialogue
        ('"Hello world"', [{"text": '"Hello world"', "type": "dialogue"}]),
        # Only exposition
        ("This is exposition", [{"text": "This is exposition", "type": "exposition"}]),
        # Simple mixed case
        (
            'He said "Hello" to her',
            [
                {"text": "He said ", "type": "exposition"},
                {"text": '"Hello"', "type": "dialogue"},
                {"text": " to her", "type": "exposition"},
            ],
        ),
        # Multiple dialogues
        (
            '"Hi" she said "Bye"',
            [
                {"text": '"Hi"', "type": "dialogue"},
                {"text": " she said ", "type": "exposition"},
                {"text": '"Bye"', "type": "dialogue"},
            ],
        ),
        # Exposition with asterisks (should be treated as exposition)
        (
            '*He walks* "Hello" *He smiles*',
            [
                {"text": "*He walks* ", "type": "exposition"},
                {"text": '"Hello"', "type": "dialogue"},
                {"text": " *He smiles*", "type": "exposition"},
            ],
        ),
        # Dialogue spanning multiple lines
        (
            'He said "Hello\nHow are you?" nicely',
            [
                {"text": "He said ", "type": "exposition"},
                {"text": '"Hello\nHow are you?"', "type": "dialogue"},
                {"text": " nicely", "type": "exposition"},
            ],
        ),
        # Complex mixed content
        (
            'The man said "I am fine" and *walked away* before saying "Goodbye"',
            [
                {"text": "The man said ", "type": "exposition"},
                {"text": '"I am fine"', "type": "dialogue"},
                {"text": " and *walked away* before saying ", "type": "exposition"},
                {"text": '"Goodbye"', "type": "dialogue"},
            ],
        ),
        # Unmatched quotes (last quote doesn't close)
        (
            'He said "Hello',
            [
                {"text": "He said ", "type": "exposition"},
                {"text": '"Hello', "type": "dialogue"},
            ],
        ),
        # Empty dialogue
        (
            'Before "" after',
            [
                {"text": "Before ", "type": "exposition"},
                {"text": '""', "type": "dialogue"},
                {"text": " after", "type": "exposition"},
            ],
        ),
        # Multiple quotes in exposition (edge case)
        (
            'She thought about the word "love" and "hate" often',
            [
                {"text": "She thought about the word ", "type": "exposition"},
                {"text": '"love"', "type": "dialogue"},
                {"text": " and ", "type": "exposition"},
                {"text": '"hate"', "type": "dialogue"},
                {"text": " often", "type": "exposition"},
            ],
        ),
        # Nested quotes scenario (treating inner quotes as part of dialogue)
        (
            "He said \"She told me 'hi' yesterday\"",
            [
                {"text": "He said ", "type": "exposition"},
                {"text": "\"She told me 'hi' yesterday\"", "type": "dialogue"},
            ],
        ),
        # Just quotes
        ('""', [{"text": '""', "type": "dialogue"}]),
        # Quotes at start and end
        (
            '"Start" middle "End"',
            [
                {"text": '"Start"', "type": "dialogue"},
                {"text": " middle ", "type": "exposition"},
                {"text": '"End"', "type": "dialogue"},
            ],
        ),
        # Single quote (unmatched)
        ('"', [{"text": '"', "type": "dialogue"}]),
        # Text ending with quote start
        (
            'Hello "',
            [
                {"text": "Hello ", "type": "exposition"},
                {"text": '"', "type": "dialogue"},
            ],
        ),
    ],
)
def test_separate_dialogue_from_exposition(input, expected):
    from talemate.util.dialogue import separate_dialogue_from_exposition

    result = separate_dialogue_from_exposition(input)

    # Convert result to list of dicts for easier comparison
    result_dicts = [{"text": chunk.text, "type": chunk.type} for chunk in result]

    assert result_dicts == expected


# New tests to validate speaker identification within dialogue chunks


@pytest.mark.parametrize(
    "input, expected",
    [
        # Single dialogue with speaker
        (
            '"{John}I am leaving now."',
            [
                {"text": '"I am leaving now."', "type": "dialogue", "speaker": "John"},
            ],
        ),
        # Dialogue embedded within exposition, with speaker
        (
            'She whispered "{Alice}Be careful" before disappearing.',
            [
                {"text": "She whispered ", "type": "exposition", "speaker": None},
                {"text": '"Be careful"', "type": "dialogue", "speaker": "Alice"},
                {
                    "text": " before disappearing.",
                    "type": "exposition",
                    "speaker": None,
                },
            ],
        ),
        # Multiple dialogues with different speakers
        (
            '"{Bob}Hi" she replied "{Carol}Hello"',
            [
                {"text": '"Hi"', "type": "dialogue", "speaker": "Bob"},
                {"text": " she replied ", "type": "exposition", "speaker": None},
                {"text": '"Hello"', "type": "dialogue", "speaker": "Carol"},
            ],
        ),
        # Prev speaker
        (
            '"{Bob}First dialog" some exposition "Second dialog" some more expostition "{Sarah}Third dialog"',
            [
                {"text": '"First dialog"', "type": "dialogue", "speaker": "Bob"},
                {"text": " some exposition ", "type": "exposition", "speaker": None},
                {"text": '"Second dialog"', "type": "dialogue", "speaker": "Bob"},
                {
                    "text": " some more expostition ",
                    "type": "exposition",
                    "speaker": None,
                },
                {"text": '"Third dialog"', "type": "dialogue", "speaker": "Sarah"},
            ],
        ),
    ],
)
def test_separate_dialogue_from_exposition_speaker(input, expected):
    """Ensure that speakers wrapped in curly-braces at the start of a dialogue segment
    are correctly extracted into the `speaker` field and removed from the `text`."""
    from talemate.util.dialogue import separate_dialogue_from_exposition

    result = separate_dialogue_from_exposition(input)

    # Convert result to list of dicts including the speaker field for comparison
    result_dicts = [
        {"text": chunk.text, "type": chunk.type, "speaker": chunk.speaker}
        for chunk in result
    ]

    assert result_dicts == expected


# Tests for the new TTS markup format parsing
@pytest.mark.parametrize(
    "input, expected",
    [
        # Empty input
        ("", []),
        # Simple narrator line
        (
            "[Narrator] He walked into the room.",
            [
                {
                    "text": "He walked into the room.",
                    "type": "exposition",
                    "speaker": None,
                }
            ],
        ),
        # Simple dialogue line
        (
            "[John] Hello world.",
            [{"text": "Hello world.", "type": "dialogue", "speaker": "John"}],
        ),
        # Mixed dialogue and narration
        (
            "[Narrator] He said\n[John] Hello world\n[Narrator] and walked away.",
            [
                {"text": "He said", "type": "exposition", "speaker": None},
                {"text": "Hello world", "type": "dialogue", "speaker": "John"},
                {"text": "and walked away.", "type": "exposition", "speaker": None},
            ],
        ),
        # Multiple speakers
        (
            "[John] Hi there\n[Mary] Hello back\n[John] How are you?",
            [
                {"text": "Hi there", "type": "dialogue", "speaker": "John"},
                {"text": "Hello back", "type": "dialogue", "speaker": "Mary"},
                {"text": "How are you?", "type": "dialogue", "speaker": "John"},
            ],
        ),
        # Line without proper format (fallback to exposition)
        (
            "Some random text without brackets",
            [
                {
                    "text": "Some random text without brackets",
                    "type": "exposition",
                    "speaker": None,
                }
            ],
        ),
        # Empty lines should be ignored
        (
            "[John] Hello\n\n[Mary] Hi\n",
            [
                {"text": "Hello", "type": "dialogue", "speaker": "John"},
                {"text": "Hi", "type": "dialogue", "speaker": "Mary"},
            ],
        ),
        # Different narrator casings
        (
            "[NARRATOR] Some narration\n[narrator] More narration",
            [
                {"text": "Some narration", "type": "exposition", "speaker": None},
                {"text": "More narration", "type": "exposition", "speaker": None},
            ],
        ),
    ],
)
def test_parse_tts_markup(input, expected):
    """Test the parse_tts_markup function that handles the new [Speaker] format."""
    from talemate.util.dialogue import parse_tts_markup

    result = parse_tts_markup(input)

    # Convert result to list of dicts for easier comparison
    result_dicts = [
        {"text": chunk.text, "type": chunk.type, "speaker": chunk.speaker}
        for chunk in result
    ]

    assert result_dicts == expected


# Tests for strip_hidden_markers function
@pytest.mark.parametrize(
    "input, hide_brackets, hide_parentheses, expected",
    [
        # No hiding - text unchanged
        ("Hello [action] world", False, False, "Hello [action] world"),
        ("Hello (thought) world", False, False, "Hello (thought) world"),
        # Hide brackets only
        ("Hello [action] world", True, False, "Hello world"),
        ("Hello (thought) world", True, False, "Hello (thought) world"),
        # Hide parentheses only
        ("Hello [action] world", False, True, "Hello [action] world"),
        ("Hello (thought) world", False, True, "Hello world"),
        # Hide both
        ("Hello [action] (thought) world", True, True, "Hello world"),
        # Whitespace collapsing - space on both sides
        ('"Hello." [walks away] "Goodbye."', True, False, '"Hello." "Goodbye."'),
        ('"Hello." (thinks) "Goodbye."', False, True, '"Hello." "Goodbye."'),
        # Whitespace - leading/trailing stripped from final result
        ("[action] Hello", True, False, "Hello"),
        ("Hello [action]", True, False, "Hello"),
        ("Hello[action]world", True, False, "Helloworld"),
        # Multiple markers - leading/trailing stripped from final result
        ("[first] Hello [second] world [third]", True, False, "Hello world"),
        ("(first) Hello (second) world (third)", False, True, "Hello world"),
        # Nested markers - outer wins
        ("[action (with thought)]", True, False, ""),
        ("[action (with thought)]", True, True, ""),
        ("[action (with thought)]", False, True, "[action ]"),
        # Multiline content
        ("Hello [multi\nline\naction] world", True, False, "Hello world"),
        ("Hello (multi\nline\nthought) world", False, True, "Hello world"),
        # Empty text
        ("", True, True, ""),
        # No markers
        ("Hello world", True, True, "Hello world"),
        # Adjacent to punctuation - space on one side is preserved
        ("Hello.[action] Goodbye.", True, False, "Hello. Goodbye."),
        ("Hello. [action]Goodbye.", True, False, "Hello. Goodbye."),
        # Complex sentence
        (
            'She said "Hello." [waves hand] (thinking about leaving) Then left.',
            True,
            True,
            'She said "Hello." Then left.',
        ),
        # Only markers - should result in empty text
        ("[action]", True, False, ""),
        ("(thought)", False, True, ""),
        ("[action] (thought)", True, True, ""),
    ],
)
def test_strip_hidden_markers(input, hide_brackets, hide_parentheses, expected):
    """Test the strip_hidden_markers function for filtering brackets and parentheses."""
    from talemate.util.dialogue import strip_hidden_markers

    result = strip_hidden_markers(
        input,
        hide_brackets=hide_brackets,
        hide_parentheses=hide_parentheses,
    )

    assert result == expected
