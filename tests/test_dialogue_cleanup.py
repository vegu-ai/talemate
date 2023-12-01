import pytest
from talemate.util import ensure_dialog_format

@pytest.mark.parametrize("input, expected", [
    ('Hello how are you?', 'Hello how are you?'),
    ('"Hello how are you?"', '"Hello how are you?"'),
    ('"Hello how are you?" he asks "I am fine"', '"Hello how are you?" *he asks* "I am fine"'),
    ('Hello how are you? *he asks* I am fine', '"Hello how are you?" *he asks* "I am fine"'),
    
    ('Hello how are you?" *he asks* I am fine', '"Hello how are you?" *he asks* "I am fine"'),
    ('Hello how are you?" *he asks I am fine', '"Hello how are you?" *he asks I am fine*'),
    ('Hello how are you?" *he asks* "I am fine" *', '"Hello how are you?" *he asks* "I am fine"'),
    
    ('"Hello how are you *he asks* I am fine"', '"Hello how are you" *he asks* "I am fine"'),
    ('This is a string without any markers', 'This is a string without any markers'),
    ('This is a string with an ending quote"', '"This is a string with an ending quote"'),
    ('This is a string with an ending asterisk*', '*This is a string with an ending asterisk*'),
    ('"Mixed markers*', '*Mixed markers*'),
])
def test_dialogue_cleanup(input, expected):
    assert ensure_dialog_format(input) == expected