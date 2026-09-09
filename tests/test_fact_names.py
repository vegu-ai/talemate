import pytest

from talemate.knowledge.chronology import DAY, fact_chronology
from talemate.knowledge.graph import facts_about
from talemate.knowledge.names import aliases_for, mentions
from talemate.knowledge.schema import Fact


@pytest.mark.parametrize(
    "subjects,eligible", [(["ship"], False), (["Will"], True), ([], True)]
)
def test_will_free_text_is_only_a_fallback_without_subjects(scene, subjects, eligible):
    scene.ts = 1000 * DAY
    scene.active_characters = ["Will"]
    fact = Fact(
        id="F1",
        text="The ship will dock tomorrow.",
        subjects=subjects,
        ts=0,
        importance=1,
    )
    assert fact_chronology(scene, fact).eligible is eligible


@pytest.mark.parametrize("subjects", [["C++"], []])
def test_punctuation_name_survives_chronology_floor(scene, subjects):
    scene.ts = 1000 * DAY
    scene.active_characters = ["C++"]
    fact = Fact(
        id="F1", text="C++ owns the observatory.", subjects=subjects, ts=0, importance=1
    )
    assert fact_chronology(scene, fact).eligible


@pytest.mark.parametrize(
    "text,found",
    [
        ("C++ owns it.", True),
        ("Talk to (C++).", True),
        ("XC++ owns it.", False),
        ("C++bot owns it.", False),
        ("Nothing relevant.", False),
    ],
)
def test_punctuation_fallback_uses_word_boundaries_outside_name(text, found):
    assert mentions(Fact(id="F1", text=text), {"c++"}, subjects_first=True) is found


def test_present_alias_subject_is_normalized_and_text_cannot_override_it(scene):
    scene.ts = 1000 * DAY
    scene.active_characters = ["Edwin"]
    scene.world_state.character_name_mappings = {"Edwin": [" the Keeper ", "Halloran"]}
    assert aliases_for(scene, " HALLORAN ") == {"edwin", "the keeper", "halloran"}
    fact = Fact(
        id="F1",
        text="An unrelated account.",
        subjects=[" THE KEEPER "],
        ts=0,
        importance=1,
    )
    assert fact_chronology(scene, fact).eligible
    fact.subjects = ["ship"]
    fact.text = "The keeper will sail."
    assert not fact_chronology(scene, fact).eligible


def test_graph_keeps_text_search_while_chronology_prefers_subjects(scene):
    scene.ts = DAY
    fact = Fact(
        id="F1", text="Mara keeps the sextant.", subjects=["sextant"], ts=scene.ts
    )
    scene.world_state.facts[fact.id] = fact
    assert facts_about(scene, "Mara") == [fact]
    assert mentions(fact, {"mara"})
    assert not mentions(fact, {"mara"}, subjects_first=True)


def test_empty_aliases_do_not_match_everything(scene):
    scene.world_state.character_name_mappings = {"": [" "]}
    assert aliases_for(scene, " ") == set()
    assert not mentions(Fact(id="F1", text="Anything"), {""})
