"""Unit tests for talemate.util.strings."""

import pytest

from talemate.util import replace_smart_quotes
from talemate.util.dialogue import separate_dialogue_from_exposition


class TestReplaceSmartQuotes:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("“Hello”", '"Hello"'),
            ("‘Hello’", "'Hello'"),
            (
                "Alice: “Hi there.” She waves. ‘Really.’",
                "Alice: \"Hi there.\" She waves. 'Really.'",
            ),
            # mixed straight / typographic, as seen in issue #173
            (
                'Alice: "When the equations refuse to sing.”',
                'Alice: "When the equations refuse to sing."',
            ),
            # German-style low-9 opening quotes pair with the marks above
            ("Alice: „Hallo“", 'Alice: "Hallo"'),
            ("Alice: ‚Hallo‘", "Alice: 'Hallo'"),
        ],
    )
    def test_replaces(self, text, expected):
        assert replace_smart_quotes(text) == expected

    def test_leaves_straight_quotes_untouched(self):
        text = 'Alice: "Hello!" She waves. It\'s fine.'
        assert replace_smart_quotes(text) == text

    def test_handles_empty_input(self):
        assert replace_smart_quotes("") == ""

    def test_quote_pairs_stay_balanced_for_the_dialogue_parser(self):
        # mapping only one mark of a pair would leave a single unbalanced
        # straight quote, and the parser would then read the trailing
        # narration as dialogue
        line = "Alice: „Hallo“ she said, then waved."
        chunks = separate_dialogue_from_exposition(replace_smart_quotes(line))
        assert [(c.type, c.text) for c in chunks] == [
            ("exposition", "Alice: "),
            ("dialogue", '"Hallo"'),
            ("exposition", " she said, then waved."),
        ]
