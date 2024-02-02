import pytest
from talemate.util import strip_partial_sentences, strip_partial_sentences_old


@pytest.mark.parametrize("input, expected", [
    ("This is a test{delim} This is a test{delim}", "This is a test{delim} This is a test{delim}"),
    ("This is a test{delim} This is a test", "This is a test{delim}"),
    ("This is a test{delim}\nThis is a test", "This is a test{delim}"),
])
def test_strip_partial_sentences(input, expected):
    
    delimiters = [".", "!", "?", '"', "*"]
    
    for delim in delimiters:
        input = input.format(delim=delim)
        expected = expected.format(delim=delim)
        assert strip_partial_sentences(input) == expected
        assert strip_partial_sentences_old(input) == expected