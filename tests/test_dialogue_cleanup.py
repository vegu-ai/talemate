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
        (
            "bob: says something\nalice: says something else",
            "bob: says something",
            "bob",
        ),
        ("bob: says a sentence. then a", "bob: says a sentence.", "bob"),
        (
            "bob: first paragraph\n\nsecond paragraph",
            "bob: first paragraph\n\nsecond paragraph",
            "bob",
        ),
        # movie script new speaker cutoff
        (
            "bob: says a sentence\n\nALICE\nsays something else",
            "bob: says a sentence",
            "bob",
        ),
    ],
)
def test_clean_dialogue(input, expected, main_name):
    assert clean_dialogue(input, main_name) == expected


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
