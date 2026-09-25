import json
from unittest.mock import AsyncMock

import pytest

from talemate.agents.summarize.perceptions import (
    PerceptionValidationError,
    exclusion_errors,
    parse_perceptions,
    passage_sentences,
)
from talemate.character import Character
from talemate.context import ActiveScene
from talemate.instance import get_agent
from talemate.prompts import Prompt
from talemate.scene_message import CharacterMessage

WHISPER = (
    'Alice: I leaned close to Bob. "The key is in the blue vase," I whispered, '
    "too softly for Cora to hear. A floorboard creaked under my heel."
)
PRETENCE = (
    "Alice: I let my eyes fall shut and pretended to sleep, though I heard every "
    'word. Bob set the blue vase on the sill. "She\'s out cold," he muttered.'
)
DOOR = (
    'Alice leaned close to Bob. "The key is in the blue vase," she said quietly. '
    "The kitchen door was thin, and Cora, at the sink, could hear every word."
)
CHESS = (
    "Alice: She drummed two fingers beside the board—tap, tap. Playing chess with "
    "Bob was her one private delight. Beneath the table, unseen by anyone else, she "
    'hid a brass key in her cuff. "Your turn," she said. Rain rattled the glass.'
)
READER = (
    "What does Alice keep hidden in her locked drawer?\n"
    "A sapphire stolen from Mira lay under the false bottom."
)


def test_sentences_split_after_closing_quotes_and_line_breaks():
    text = 'Alice: "Hello." She smiled.\nA bell rang!'
    assert [text[start:end] for start, end in passage_sentences(text)] == [
        'Alice: "Hello."',
        "She smiled.",
        "A bell rang!",
    ]


def test_sentences_split_after_emphasis_markup_and_investigation_headings():
    thought = 'Alice: *I hate him.* "Hello, Bob!" *He must never know.* "Nice day."'
    assert [thought[start:end] for start, end in passage_sentences(thought)] == [
        "Alice: *I hate him.*",
        '"Hello, Bob!"',
        "*He must never know.*",
        '"Nice day."',
    ]
    note = "# Internal note for Alice - Where is the key?\nIt lies in the vase."
    assert [note[start:end] for start, end in passage_sentences(note)] == [
        "# Internal note for Alice - Where is the key?",
        "It lies in the vase.",
    ]


def test_sentences_continue_into_a_lowercase_speech_tag_and_close_after_braces():
    tag = (
        'Bob looked up. "Is the key in the blue vase?" she whispered to him. Cora ate.'
    )
    assert [tag[start:end] for start, end in passage_sentences(tag)] == [
        "Bob looked up.",
        '"Is the key in the blue vase?" she whispered to him.',
        "Cora ate.",
    ]
    for passage, first in (
        ('Alice said {"Run!"} Bob hid the key. Carol waved.', 'Alice said {"Run!"}'),
        ("«Cours !» Bob hid the key. Carol waved.", "«Cours !»"),
    ):
        start, end = passage_sentences(passage)[0]
        assert passage[start:end] == first


@pytest.mark.parametrize(
    "passage,span,text",
    [
        (
            'Bob looked up. "Is the key in the blue vase?" she whispered to him. '
            "Cora kept washing.",
            '"Is the key in the blue vase?"',
            "Bob looked up. She whispered something to him. Cora kept washing.",
        ),
        (
            '"Run!" she hissed at Bob. The guards turned.',
            '"Run!"',
            "She hissed something at Bob. The guards turned.",
        ),
        (
            'Alice: I leaned close to Bob. "Is the key in the blue vase?" I whispered '
            "to him. Cora kept washing.",
            '"Is the key in the blue vase?"',
            "Alice: I leaned close to Bob. I whispered something to him. Cora kept "
            "washing.",
        ),
        (
            'Alice: "The key is in the blue vase." *I lean close and whisper it to '
            "Bob.* A floorboard creaks.",
            "The key is in the blue vase.",
            "Alice: *I lean close and whisper something to Bob.* A floorboard creaks.",
        ),
        (
            'She leaned in. "The key is in the blue vase". I whispered to him. '
            "Cora kept washing.",
            '"The key is in the blue vase"',
            "She leaned in. I whispered something to him. Cora kept washing.",
        ),
        (
            "Elle se pencha. «Le secret est ici». Il chuchota. Cora regardait.",
            "«Le secret est ici»",
            "Elle se pencha. Il chuchota quelque chose. Cora regardait.",
        ),
        (
            'She leaned in. *"The key is in the blue vase."* I whispered to him. '
            "Cora kept washing.",
            '"The key is in the blue vase."',
            "She leaned in. I whispered something to him. Cora kept washing.",
        ),
        (
            'She leaned in. ("The key is in the blue vase.") I whispered to him. '
            "Cora kept washing.",
            '"The key is in the blue vase."',
            "She leaned in. I whispered something to him. Cora kept washing.",
        ),
    ],
)
def test_host_check_accepts_the_kept_act_after_a_removed_quote(passage, span, text):
    assert exclusion_errors(passage, (span,), text) == []


@pytest.mark.parametrize(
    "passage,span,text",
    [
        (
            'Alice: I leaned close to Bob. "Is the key in the blue vase?" I whispered '
            "to him. Cora kept washing.",
            '"Is the key in the blue vase?"',
            "Alice: I leaned close to Bob. I whispered something to him. Cora smiled.",
        ),
        (
            "«Cours !» Bob hid the key. Carol waved.",
            "Bob hid the key.",
            "«Cours !» Something else. Carol smiled.",
        ),
        (
            'She leaned in. "The key is in the blue vase, Bob." I whispered to him. '
            "Cora kept washing.",
            '"The key is in the blue vase',
            'She leaned in. "Bob." I whispered something to him. Cora kept washing.',
        ),
        (
            "Alice whispered the plan.\n***\nBob left. Cora ate.",
            "plan.\n***",
            "Alice whispered something.\nSomething invented. Cora ate.",
        ),
    ],
)
def test_host_check_keeps_sentences_beyond_the_speech_tag(passage, span, text):
    assert any(
        "missing or changed" in error
        for error in exclusion_errors(passage, (span,), text)
    )


@pytest.mark.parametrize(
    "passage,span,text",
    [
        (
            'Bob asked, "Coming?" "Yes," Alice whispered to Cora. "Yes," Alice said '
            "aloud to Bob.",
            '"Yes," ',
            'Bob asked, "Coming?" Alice whispered something to Cora. "Yes," Alice said '
            "aloud to Bob.",
        ),
        (
            "Alice thought of the key. The monkey screeched.",
            "key",
            "Alice thought of something. The monkey screeched.",
        ),
        ("Alice smiled. Bob waved. The bell rang.", ".", "Something else happened"),
        ("Alice laughed: ha ha ha.", "ha ha", "Alice laughed: ha."),
    ],
)
def test_host_check_rejects_a_span_that_is_not_unique(passage, span, text):
    errors = exclusion_errors(passage, (span,), text)
    assert any("occurs 2 times" in e or "occurs 3 times" in e for e in errors)


def test_host_check_rejects_a_rewrite_after_an_emphasized_thought():
    passage = 'Alice: *I loved playing chess with Bob.* "Your turn," I said. Rain fell.'
    assert exclusion_errors(
        passage,
        ("I loved playing chess with Bob.",),
        'Alice: *I was playing chess with Bob.* "Checkmate," I shouted. Rain fell.',
    ) == [
        "sentence outside the exclusions is missing or changed: '\"Your turn,\" I said.'"
    ]


@pytest.mark.parametrize(
    "passage,spans,text",
    [
        (WHISPER, [], WHISPER),
        (
            WHISPER,
            ['"The key is in the blue vase,"'],
            "Alice: I leaned close to Bob. I whispered something, too softly for "
            "Cora to hear. A floorboard creaked under my heel.",
        ),
        (
            PRETENCE,
            [" and pretended to sleep, though I heard every word"],
            PRETENCE.replace(" and pretended to sleep, though I heard every word", ""),
        ),
        (
            DOOR,
            [", and Cora, at the sink, could hear every word"],
            'Alice leaned close to Bob. "The key is in the blue vase," she said '
            "quietly. The kitchen door was thin.",
        ),
        (
            CHESS,
            [
                "Playing chess with Bob was her one private delight.",
                "Beneath the table, unseen by anyone else, she hid a brass key in "
                "her cuff.",
            ],
            "Alice: She drummed two fingers beside the board—tap, tap. She was "
            'playing chess with Bob. "Your turn," she said. Rain rattled the glass.',
        ),
        (
            "From the dark hayloft, Dorian watched Alice pass the letter to Bob.",
            ["From the dark hayloft, Dorian watched "],
            "Alice passed the letter to Bob.",
        ),
    ],
)
def test_host_check_accepts_deletions_and_local_edits_at_spans(passage, spans, text):
    assert exclusion_errors(passage, tuple(spans), text) == []


@pytest.mark.parametrize(
    "passage,spans,text,reason",
    [
        (
            WHISPER,
            [],
            WHISPER.replace("Alice: I leaned", "Alice: Alice leaned"),
            "missing or changed",
        ),
        (
            WHISPER,
            ['"The key is in the blue vase,"'],
            "Alice: I leaned close to Bob. I whispered something. ",
            "missing or changed",
        ),
        (WHISPER, [], "Bob sees: " + WHISPER, "text added"),
        (WHISPER, [], WHISPER + " Cora saw it.", "text added"),
        (
            CHESS,
            ["Playing chess with Bob was her one private delight."],
            CHESS.replace(
                "Playing chess with Bob was her one private delight.",
                "She was playing chess with Bob.",
            ).replace('"Your turn,"', 'He waited. "Your turn,"'),
            "text added",
        ),
        (WHISPER, ['"The key is in the blue vase,"'], WHISPER, "still in the text"),
        (WHISPER, ["the red vase"], WHISPER, "not in the passage"),
        (
            READER,
            [],
            "What does Alice keep hidden in her locked drawer?",
            "missing or changed",
        ),
    ],
)
def test_host_check_rejects_text_outside_the_spans(passage, spans, text, reason):
    errors = exclusion_errors(passage, tuple(spans), text)
    assert any(reason in error for error in errors), errors


def payload(*views):
    return json.dumps({"views": list(views)})


def view(name, text, exclusions=None, status="ready"):
    entry = {
        "audience": [name],
        "status": status,
        "text": text,
        "knowledge_ids": [],
        "passage_ids": [],
    }
    if exclusions is not None:
        entry["exclusions"] = exclusions
    return entry


def test_parser_rejects_a_view_that_fails_the_host_check_and_keeps_its_sibling():
    response = payload(
        view("Alice", WHISPER, []),
        view(
            "Cora",
            "Alice: I leaned close to Bob. I whispered something, too softly for "
            "Cora to hear.",
            [{"span": '"The key is in the blue vase,"', "reason": "inaudible"}],
        ),
    )
    with pytest.raises(PerceptionValidationError) as error:
        parse_perceptions(response, ("Alice", "Cora"), WHISPER)
    assert [v.audience for v in error.value.views] == [("Alice",)]
    assert "Cora: text does not match its exclusions" in str(error.value)
    assert "A floorboard creaked under my heel." in str(error.value)


def test_host_check_cannot_see_edits_inside_a_sentence_that_touches_a_span():
    # The check verifies text against the exclusions, not the exclusions
    # themselves: losing the whisper act inside the edited sentence passes.
    assert (
        exclusion_errors(
            WHISPER,
            ('"The key is in the blue vase,"',),
            "Alice: I leaned close to Bob. A floorboard creaked under my heel.",
        )
        == []
    )


@pytest.mark.parametrize(
    "exclusions",
    [None, {}, "all", [None], [{"span": "Alice"}], [{"span": " ", "reason": "x"}]],
)
def test_ready_views_need_a_readable_exclusion_array(exclusions):
    entry = view("Alice", WHISPER)
    if exclusions is not None:
        entry["exclusions"] = exclusions
    with pytest.raises(PerceptionValidationError, match="Alice: .*exclusion"):
        parse_perceptions(payload(entry), ("Alice",), WHISPER)


def test_omitted_views_need_no_exclusions():
    views = parse_perceptions(
        payload(view("Dorian", None, status="omitted")), ("Dorian",), WHISPER
    )
    assert views[0].status == "omitted"


def test_prompt_orders_exclusions_before_text(scene):
    rendered = Prompt.get(
        "summarizer.perceptions",
        vars={"scene": scene, "context": {}, "validation_error": ""},
    ).render()
    assert "STEP 1, EXCLUSIONS" in rendered
    assert "STEP 2, TEXT" in rendered
    shape = rendered[rendered.index("Example shape:") :]
    assert shape.index('"exclusions"') < shape.index('"text"')


@pytest.fixture
def analysis(scene, monkeypatch):
    scene.knowledge_eligibility = "perception"
    scene.character_data = {name: Character(name=name) for name in ("Alice", "Bob")}
    scene.active_characters = ["Alice", "Bob"]
    summarizer = get_agent("summarizer")
    request = AsyncMock()
    dialog = AsyncMock(return_value="cancel")
    monkeypatch.setattr("talemate.agents.summarize.perceptions.Prompt.request", request)
    monkeypatch.setattr(summarizer.client, "_prompt_generation_error", dialog)
    with ActiveScene(scene):
        yield scene, summarizer, request, dialog


async def test_host_check_failure_goes_through_the_repair_path(analysis):
    scene, summarizer, request, dialog = analysis
    assert summarizer.resolve_config("perceptions", "automatic_repair") is True
    passage = "Alice: I waved. The key is mine, I thought."
    bad = payload(
        view("Alice", passage, []),
        view("Bob", "Alice: I waved.", []),
    )
    good = payload(
        view(
            "Bob",
            "Alice: I waved.",
            [{"span": "The key is mine, I thought.", "reason": "private-thought"}],
        )
    )
    request.side_effect = [(bad, {"response": bad}), (good, {"response": good})]
    message = CharacterMessage(message=passage)
    await scene.push_history(message)
    assert request.await_count == 2
    repair = request.await_args_list[1].kwargs["vars"]
    assert [entry["name"] for entry in repair["context"]["cast"]] == ["Bob"]
    assert "The key is mine, I thought." in repair["validation_error"]
    assert "missing or changed" in repair["validation_error"]
    alice, bob = message.knowledge.views
    assert alice.text == passage
    assert bob.text == "Alice: I waved."
    dialog.assert_not_awaited()
