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
