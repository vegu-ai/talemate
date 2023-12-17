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
    ('"*Nodding thoughtfully.* That does make sense. Creating your own world where you set the rules must be incredibly liberating. And yes, AI could revolutionize gaming in many ways. Have you ever considered incorporating elements of anthropology or cultural aspects into your game concepts?" *She asks, intrigued by the idea.*', '*Nodding thoughtfully.* "That does make sense. Creating your own world where you set the rules must be incredibly liberating. And yes, AI could revolutionize gaming in many ways. Have you ever considered incorporating elements of anthropology or cultural aspects into your game concepts?" *She asks, intrigued by the idea.*'),
    ('"*Her eyes light up with curiosity.* Oh, a game sounds fun! What do you have in mind?" *She watches as Jake rummages through his backpack, pulling out a deck of cards.*"', '*Her eyes light up with curiosity.* "Oh, a game sounds fun! What do you have in mind?" *She watches as Jake rummages through his backpack, pulling out a deck of cards.*'),
])
def test_dialogue_cleanup(input, expected):
    assert ensure_dialog_format(input) == expected