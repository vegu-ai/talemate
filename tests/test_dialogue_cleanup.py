import pytest
from talemate.util import ensure_dialog_format, clean_dialogue

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
    ('*narrative.* dialogue" *more narrative.*', '*narrative.* "dialogue" *more narrative.*'),
    ('"*messed up dialogue formatting.*" *some narration.*', '"messed up dialogue formatting." *some narration.*'),
    ('*"messed up narration formatting."* "some dialogue."', '"messed up narration formatting." "some dialogue."'),
])
def test_dialogue_cleanup(input, expected):
    assert ensure_dialog_format(input) == expected
    
    
@pytest.mark.parametrize("input, expected, main_name", [
    ("bob: says a sentence", "bob: says a sentence", "bob"),
    ("bob: says a sentence\nbob: says another sentence", "bob: says a sentence\nsays another sentence", "bob"),
    ("bob: says a sentence with a colon: to explain something", "bob: says a sentence with a colon: to explain something", "bob"),
    ("bob: i have a riddle for you, alice: the riddle", "bob: i have a riddle for you, alice: the riddle", "bob"),
    ("bob: says something\nalice: says something else", "bob: says something", "bob"),
    ("bob: says a sentence. then a", "bob: says a sentence.", "bob"),
    ("bob: first paragraph\n\nsecond paragraph", "bob: first paragraph\n\nsecond paragraph", "bob"),
    # movie script new speaker cutoff
    ("bob: says a sentence\n\nALICE\nsays something else", "bob: says a sentence", "bob"),
])
def test_clean_dialogue(input, expected, main_name):
    others = ["alice", "charlie"]
    assert clean_dialogue(input, main_name) == expected