from _knowledge_step_helpers import push_and_step
import json
from unittest.mock import AsyncMock

import pytest

from talemate.agents.summarize.perceptions import (
    PerceptionExclusion,
    PerceptionValidationError,
    exclusion_errors,
    forbidden_in_text,
    parse_perceptions,
    passage_sentences,
    rewrite_regions,
)
from talemate.character import Character
from talemate.context import ActiveScene
from talemate.instance import get_agent
from talemate.prompts import Prompt
from talemate.scene_message import CharacterMessage


def exclusion(span, forbidden=(), trace=None):
    return PerceptionExclusion(
        span=span, reason="private", forbidden=list(forbidden), trace=trace
    )


def payload(*views):
    return json.dumps({"views": list(views)})


def view(name, text, exclusions=None, status="ready"):
    result = {
        "audience": [name],
        "status": status,
        "text": text,
        "knowledge_ids": [],
        "passage_ids": [],
    }
    if exclusions is not None:
        result["exclusions"] = [
            item.model_dump() if isinstance(item, PerceptionExclusion) else item
            for item in exclusions
        ]
    return result


def test_sentences_split_after_quotes_markup_and_headings():
    for text, expected in (
        (
            'Alice: "Hello." She smiled.\nA bell rang!',
            ['Alice: "Hello."', "She smiled.", "A bell rang!"],
        ),
        (
            'Alice: *I hate him.* "Hello, Bob!" *He must never know.* "Nice day."',
            [
                "Alice: *I hate him.*",
                '"Hello, Bob!"',
                "*He must never know.*",
                '"Nice day."',
            ],
        ),
        (
            "# Where is the key?\nIt lies in the vase.",
            ["# Where is the key?", "It lies in the vase."],
        ),
        (
            'Bob looked up. "Where is it?" she whispered. Cora ate.',
            ["Bob looked up.", '"Where is it?" she whispered.', "Cora ate."],
        ),
        (
            'Alice said {"Run!"} Bob hid. Carol waved.',
            ['Alice said {"Run!"}', "Bob hid.", "Carol waved."],
        ),
    ):
        assert [text[start:end] for start, end in passage_sentences(text)] == expected


SOURCE = "Rain fell. I waved. I hid the key with a clink. Bob waited. The clock ticked."
SPAN = "I hid the key with a clink."
REWRITTEN = (
    "Rain fell. I waved as a clink sounded. Bob waited nearby. The clock ticked."
)


def test_rewrite_regions_include_only_touched_sentences_and_immediate_neighbors():
    start = SOURCE.index(SPAN)
    regions = rewrite_regions(SOURCE, ((start, start + len(SPAN)),))
    assert len(regions) == 1
    assert (
        SOURCE[regions[0].start : regions[0].end]
        == " I waved. I hid the key with a clink. Bob waited. "
    )
    assert not regions[0].partial
    assert exclusion_errors(SOURCE, (exclusion(SPAN, ["key"]),), REWRITTEN) == []


@pytest.mark.parametrize(
    "changed",
    [
        REWRITTEN.replace("Rain fell.", "Rain stopped."),
        REWRITTEN.replace("The clock ticked.", "The clock chimed."),
        "Someone arrived. " + REWRITTEN,
        REWRITTEN + " Someone left.",
        REWRITTEN.replace("Rain fell.", ""),
        REWRITTEN.replace("The clock ticked.", ""),
    ],
)
def test_region_cannot_change_remove_or_add_outside_its_bounds(changed):
    assert any(
        "outside rewrite regions" in e
        for e in exclusion_errors(SOURCE, (exclusion(SPAN),), changed)
    )


@pytest.mark.parametrize(
    "text",
    [
        SOURCE + " ",
        " " + SOURCE,
        SOURCE.replace(". ", ".\n", 1),
        SOURCE.replace("Rain", "Snow"),
    ],
)
def test_without_exclusions_the_entire_passage_stays_byte_identical(text):
    assert exclusion_errors(SOURCE, (), text)
    assert exclusion_errors(SOURCE, (), SOURCE) == []


@pytest.mark.parametrize(
    "text,token,found",
    [
        ("A KEY fell.", "key", True),
        ("The monkey used a keyboard.", "key", False),
        ("The silver\nkey fell.", "silver key", True),
        ("A silver keyboard.", "silver key", False),
        ("(Mira's ring)", "Mira's ring", True),
        ("A BRASS KEY!", "brass key", True),
        ("A keyhole.", "key", False),
        ("Her keys.", "key", False),
    ],
)
def test_forbidden_check_uses_case_insensitive_whole_tokens_and_phrases(
    text, token, found
):
    assert forbidden_in_text(text, token) is found


def test_unchanged_block_keeps_its_internal_whitespace_byte_identical():
    source = "I hid a key. Bob waited. Rain fell.\n\nThe clock ticked. Cora nodded. I hid a ring."
    edits = (exclusion("I hid a key."), exclusion("I hid a ring."))
    accepted = "Bob waited. Rain fell.\n\nThe clock ticked. Cora nodded."
    assert exclusion_errors(source, edits, accepted) == []
    assert exclusion_errors(source, edits, accepted.replace("\n\n", " "))


def test_forbidden_check_catches_a_secret_even_when_the_excluded_span_is_gone():
    text = REWRITTEN.replace("a clink", "a KEY's clink")
    errors = exclusion_errors(SOURCE, (exclusion(SPAN, ["key"]),), text)
    assert errors == ["forbidden content in rewrite region: ['key']"]


def test_a_forbidden_word_in_unchanged_text_does_not_make_it_editable():
    source = (
        "The key lay there. Bob smiled. I hid a second key. Cora waited. Rain fell."
    )
    text = "The key lay there. Bob smiled. Cora waited. Rain fell."
    assert (
        exclusion_errors(source, (exclusion("I hid a second key.", ["key"]),), text)
        == []
    )


def test_excluded_span_itself_cannot_remain_even_with_an_empty_forbidden_list():
    assert any(
        "still in the text" in e
        for e in exclusion_errors(SOURCE, (exclusion(SPAN),), SOURCE)
    )


@pytest.mark.parametrize(
    "span,reason", [("missing", "not in the passage"), ("ha ha", "occurs 2 times")]
)
def test_source_spans_must_exist_and_be_unique(span, reason):
    assert any(
        reason in e
        for e in exclusion_errors(
            "Alice laughed: ha ha ha.", (exclusion(span),), "Alice laughed."
        )
    )


@pytest.mark.parametrize("result", ["", "  ", "\n\t"])
def test_partially_excluded_sentence_needs_a_nonempty_region(result):
    assert exclusion_errors(
        "I whispered a secret.", (exclusion("a secret", ["secret"]),), result
    ) == ["a partially excluded sentence needs a nonempty rewrite region"]


def test_full_sentence_exclusion_may_leave_an_empty_region():
    assert (
        exclusion_errors("I hid a key.", (exclusion("I hid a key.", ["key"]),), "")
        == []
    )


@pytest.mark.parametrize("result", ["", "  ", "\n\t"])
def test_wholly_excluded_merged_region_may_be_empty(result):
    source = "I hid a key.\n \tI hid a ring."
    edits = (exclusion("I hid a key."), exclusion("I hid a ring."))
    assert exclusion_errors(source, edits, result) == []


@pytest.mark.parametrize(
    "source,rewritten",
    [
        (
            "Alice smiled. Bob hid the key under the rug. Carol left. Dan sat. Eve slept.",
            "Dan sat. Eve slept.",
        ),
        ("🔔\nBob hid the key under the rug.", " \n"),
        ("Bob hid the key under the rug. Carol left.", ""),
    ],
)
def test_full_sentence_exclusion_cannot_erase_unexcluded_neighbors(source, rewritten):
    assert exclusion_errors(
        source, (exclusion("Bob hid the key under the rug.", ["key"]),), rewritten
    ) == ["a rewrite region with unexcluded source text must be nonempty"]


def test_excluding_words_but_leaving_punctuation_is_partial():
    assert exclusion_errors(
        "I hid a key.", (exclusion("I hid a key", ["key"]),), ""
    ) == ["a partially excluded sentence needs a nonempty rewrite region"]


def test_nonempty_region_can_retain_meaningful_symbols():
    source = "🔔 — secretly a signal."
    edits = (exclusion(" — secretly a signal", ["secretly", "signal"]),)
    assert exclusion_errors(source, edits, "🔔.") == []
    assert exclusion_errors(source, edits, "") == [
        "a partially excluded sentence needs a nonempty rewrite region"
    ]


def test_nonempty_check_applies_to_each_separate_region():
    source = "I whispered a secret. Bob listened. Rain fell. Cora waited. I hid a key."
    edits = (exclusion("a secret", ["secret"]), exclusion("I hid a key.", ["key"]))
    assert any(
        "nonempty" in e
        for e in exclusion_errors(source, edits, "Rain fell. Cora waited.")
    )
    assert exclusion_errors(source, edits, "I whispered. Bob listened. Rain fell.") == [
        "a rewrite region with unexcluded source text must be nonempty"
    ]
    assert (
        exclusion_errors(
            source, edits, "I whispered. Bob listened. Rain fell. Cora waited."
        )
        == []
    )


def test_declared_secrets_cannot_move_to_another_rewrite_region():
    source = "I hid the key. Bob waited. Rain fell. Cora nodded. I hid the ring."
    edits = (
        exclusion("I hid the key.", ["key"]),
        exclusion("I hid the ring.", ["ring"]),
    )
    assert any(
        "forbidden" in e
        for e in exclusion_errors(
            source, edits, "Bob waited. Rain fell. Cora nodded at the KEY."
        )
    )


def test_repeated_unchanged_anchors_do_not_force_the_first_alignment():
    source = (
        "I whispered a secret. Bob listened. Rain fell. Cora waited. I hid the ring."
    )
    edits = (exclusion("a secret", ["secret"]), exclusion("I hid the ring.", ["ring"]))
    text = "Rain fell. I whispered something. Bob listened. Rain fell. Cora waited."
    assert exclusion_errors(source, edits, text) == []
    assert exclusion_errors(source, edits, text.replace("Rain fell.", "Rain stopped."))


@pytest.mark.parametrize(
    "source,span,expected",
    [
        (
            "From the dark hayloft, Dorian watched Alice pass the letter to Bob.",
            "From the dark hayloft, Dorian watched ",
            "Alice passed the letter to Bob.",
        ),
        (
            'Playing chess with Bob was my one private delight. "Your turn," I said.',
            "was my one private delight",
            'I was playing chess with Bob. "Your turn," I said.',
        ),
        (
            'Alice taps the board twice, wishing Bob would hurry up and lose, and says, "Your move." Rain streaks the window.',
            "wishing Bob would hurry up and lose",
            'Alice taps the board twice and says, "Your move." Rain streaks the window.',
        ),
        (
            "„Der Schlüssel ist in der Vase“. Ich flüsterte es ihm zu. Regen fiel.",
            "„Der Schlüssel ist in der Vase“",
            "Ich flüsterte ihm etwas zu. Regen fiel.",
        ),
    ],
)
def test_secondary_joins_can_be_rewritten_as_grammatical_prose(source, span, expected):
    assert exclusion_errors(source, (exclusion(span),), expected) == []


def test_trace_can_be_reworded_inside_its_region_and_is_not_stored():
    response = payload(
        view(
            "Bob", REWRITTEN, [exclusion(SPAN, ["key"], "There was a clinking sound.")]
        )
    )
    result = parse_perceptions(response, ("Bob",), SOURCE)
    assert result[0].text == REWRITTEN
    assert "trace" not in result[0].model_dump()
    assert "exclusions" not in result[0].model_dump()


def test_host_does_not_claim_to_detect_a_missing_sensory_fact():
    text = "Rain fell. I waved. Bob waited. The clock ticked."
    response = payload(
        view("Bob", text, [exclusion(SPAN, ["key"], "A clink sounded.")])
    )
    assert parse_perceptions(response, ("Bob",), SOURCE)[0].text == text


@pytest.mark.parametrize(
    "item",
    [
        None,
        {},
        "all",
        [None],
        [{"span": "Alice"}],
        [{"span": " ", "reason": "x", "forbidden": []}],
        [{"span": "Alice", "reason": "x"}],
        [{"span": "Alice", "reason": "x", "forbidden": "Alice"}],
        [{"span": "Alice", "reason": "x", "forbidden": [1]}],
        [{"span": "Alice", "reason": "x", "forbidden": [""]}],
    ],
)
def test_ready_views_need_a_typed_exclusion_array_and_forbidden_lists(item):
    entry = view("Alice", SOURCE)
    if item is not None:
        entry["exclusions"] = item
    with pytest.raises(PerceptionValidationError, match="exclusion|forbidden"):
        parse_perceptions(payload(entry), ("Alice",), SOURCE)


@pytest.mark.parametrize("trace", ["", "  ", 1, True, [], {}])
def test_trace_needs_a_nonempty_string(trace):
    entry = {"span": SPAN, "reason": "unseen", "forbidden": ["key"], "trace": trace}
    with pytest.raises(PerceptionValidationError, match="trace"):
        parse_perceptions(payload(view("Bob", REWRITTEN, [entry])), ("Bob",), SOURCE)


def test_null_or_absent_trace_keeps_the_same_rewrite_contract():
    for entry in (
        exclusion(SPAN, ["key"]).model_dump(),
        {"span": SPAN, "reason": "unseen", "forbidden": ["key"]},
    ):
        assert (
            parse_perceptions(
                payload(view("Bob", REWRITTEN, [entry])), ("Bob",), SOURCE
            )[0].text
            == REWRITTEN
        )


def test_parser_keeps_valid_siblings_when_a_region_fails():
    response = payload(
        view("Alice", SOURCE, []),
        view(
            "Bob", REWRITTEN.replace("Rain fell.", "Rain stopped."), [exclusion(SPAN)]
        ),
    )
    with pytest.raises(PerceptionValidationError) as error:
        parse_perceptions(response, ("Alice", "Bob"), SOURCE)
    assert [v.audience for v in error.value.views] == [("Alice",)]
    assert "outside rewrite regions" in str(error.value)
    assert repr("Rain fell.") in str(error.value)


@pytest.mark.parametrize(
    "source,edits,rewritten,fragment",
    [
        (SOURCE, [], SOURCE.replace("Rain", "Snow"), SOURCE),
        (SOURCE, [exclusion(SPAN)], REWRITTEN.replace("Rain", "Snow"), "Rain fell."),
        (
            SOURCE,
            [exclusion(SPAN)],
            REWRITTEN.replace("The clock ticked.", "The clock chimed."),
            "The clock ticked.",
        ),
        (
            "I hid a key. Bob waited. Rain fell. Cora nodded. I hid a ring.",
            [exclusion("I hid a key."), exclusion("I hid a ring.")],
            "Bob waited. Snow fell. Cora nodded.",
            "Rain fell.",
        ),
    ],
)
def test_alignment_failure_reports_the_unchanged_fragment(
    source, edits, rewritten, fragment
):
    with pytest.raises(PerceptionValidationError) as error:
        parse_perceptions(payload(view("Bob", rewritten, edits)), ("Bob",), source)
    assert "outside rewrite regions" in str(error.value)
    assert repr(fragment) in str(error.value)


@pytest.mark.parametrize("padding", ["a", "\x01"])
def test_large_passage_error_quotes_a_bounded_window_at_the_first_difference(padding):
    source = padding * 21000 + "EXPECTED" + padding * 21000
    text = source.replace("EXPECTED", "CHANGED")
    errors = exclusion_errors(source, (), text)
    assert len(errors) == 1
    assert "EXPECTED" in errors[0]
    assert "…" in errors[0]
    assert len(errors[0]) < 500


@pytest.mark.parametrize("position", ["start", "end"])
def test_large_passage_error_handles_first_and_last_character_changes(position):
    source = "Start. " + "a" * 42000 + " End.\n"
    text = source[1:] if position == "start" else source[:-1]
    errors = exclusion_errors(source, (), text)
    assert len(errors) == 1
    assert ("Start." if position == "start" else "End.\\n") in errors[0]
    assert len(errors[0]) < 250


def test_large_unchanged_prefix_error_quotes_the_mismatch_window():
    prefix = "a" * 21000 + "EXPECTED" + "a" * 21000 + "."
    source = prefix + " I waved. I hid a key. Bob waited. Rain fell."
    text = prefix.replace("EXPECTED", "CHANGED") + " I waved. Bob waited. Rain fell."
    errors = exclusion_errors(source, (exclusion("I hid a key."),), text)
    assert len(errors) == 1
    assert "EXPECTED" in errors[0]
    assert len(errors[0]) < 250


def test_large_unchanged_anchor_error_is_bounded():
    anchor = "A long anchor " + "a" * 42000 + "."
    source = "I hid a key. Bob waited. " + anchor
    text = "Bob waited. " + anchor.replace("anchor", "fragment")
    errors = exclusion_errors(source, (exclusion("I hid a key."),), text)
    assert len(errors) == 1
    assert "A long anchor" in errors[0]
    assert len(errors[0]) < 250


def test_repeated_anchor_error_quotes_where_alignment_stopped():
    source = "A. X hid key. B. Rain fell. C. Y hid ring. D. Rain fell. End."
    edits = (exclusion("X hid key."), exclusion("Y hid ring."))
    text = "A. B. Snow fell. C. D. Rain fell. End."
    errors = exclusion_errors(source, edits, text)
    assert len(errors) == 1
    assert repr("Rain fell. End.") in errors[0]


def test_omitted_views_need_no_exclusions():
    result = parse_perceptions(
        payload(view("Bob", None, status="omitted")), ("Bob",), SOURCE
    )
    assert result[0].status == "omitted"


@pytest.mark.parametrize("enabled", [False, True])
def test_prompt_orders_exclusions_and_forbidden_content_before_text(scene, enabled):
    rendered = Prompt.get(
        "summarizer.perceptions",
        vars={
            "scene": scene,
            "context": {},
            "validation_error": "",
            "rewrite_hidden_traces": enabled,
        },
    ).render()
    assert "STEP 1, EXCLUSIONS" in rendered
    assert "STEP 2, TEXT" in rendered
    assert "rewrite region" in rendered
    assert "forbidden" in rendered
    assert ('"trace":' in rendered) is enabled
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


@pytest.mark.parametrize("enabled", [False, True])
async def test_forbidden_content_repairs_in_both_trace_modes(analysis, enabled):
    scene, summarizer, request, dialog = analysis
    assert summarizer.resolve_config("perceptions", "rewrite_hidden_traces") is False
    summarizer.actions["perceptions"].config["rewrite_hidden_traces"].value = enabled
    edits = [exclusion(SPAN, ["key"], "A clink sounded." if enabled else None)]
    bad = payload(view("Bob", REWRITTEN.replace("a clink", "a key's clink"), edits))
    good = payload(view("Bob", REWRITTEN, edits))
    request.side_effect = [(bad, {"response": bad}), (good, {"response": good})]
    message = CharacterMessage(message="Alice: " + SOURCE)
    await push_and_step(scene, message)
    assert request.await_count == 2
    for call in request.await_args_list:
        assert call.kwargs["vars"]["rewrite_hidden_traces"] is enabled
    assert "forbidden" in request.await_args.kwargs["vars"]["validation_error"]
    alice, bob = message.knowledge.views
    assert alice.text == SOURCE
    assert bob.text == REWRITTEN
    dialog.assert_not_awaited()
