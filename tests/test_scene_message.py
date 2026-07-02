"""Unit tests for talemate.scene_message message models and helpers."""

import pytest

from talemate.scene_message import (
    CharacterMessage,
    ContextInvestigationMessage,
    DIRECTOR_INPUT_PREFIX,
    DIRECTOR_INPUT_PREFIX_YIELD,
    DirectorMessage,
    Flags,
    MESSAGES,
    NarratorMessage,
    ReinforcementMessage,
    SceneMessage,
    TimePassageMessage,
    get_message_id,
    reset_message_id,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_message_id():
    """Each test starts with a clean message id counter."""
    reset_message_id()
    yield
    reset_message_id()


# ---------------------------------------------------------------------------
# Module-level constants & helpers
# ---------------------------------------------------------------------------


class TestDirectorInputPrefixes:
    def test_yield_prefix_is_two_hashes(self):
        # The yield variant must be checked first since it is a superset of the
        # single-character prefix.
        assert DIRECTOR_INPUT_PREFIX_YIELD == "##"
        assert DIRECTOR_INPUT_PREFIX == "#"
        assert DIRECTOR_INPUT_PREFIX_YIELD.startswith(DIRECTOR_INPUT_PREFIX)


class TestMessageIdHelpers:
    def test_get_message_id_increments(self):
        first = get_message_id()
        second = get_message_id()
        third = get_message_id()
        assert (first, second, third) == (1, 2, 3)

    def test_reset_message_id_returns_counter_to_zero(self):
        get_message_id()
        get_message_id()
        reset_message_id()
        assert get_message_id() == 1

    def test_default_factory_uses_global_counter(self):
        # SceneMessage default factory pulls the next id from the helper
        m1 = SceneMessage(message="hello")
        m2 = SceneMessage(message="world")
        assert m2.id == m1.id + 1


class TestMessagesRegistry:
    def test_known_types_route_to_correct_class(self):
        assert MESSAGES["scene"] is SceneMessage
        assert MESSAGES["character"] is CharacterMessage
        assert MESSAGES["narrator"] is NarratorMessage
        assert MESSAGES["director"] is DirectorMessage
        assert MESSAGES["time"] is TimePassageMessage
        assert MESSAGES["reinforcement"] is ReinforcementMessage
        assert MESSAGES["context_investigation"] is ContextInvestigationMessage

    def test_typ_attr_matches_registry_key(self):
        for key, cls in MESSAGES.items():
            default_typ = cls.model_fields["typ"].default
            assert default_typ == key, f"{cls.__name__}.typ != registry key {key!r}"


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------


class TestFlags:
    def test_none_flag_is_zero(self):
        assert int(Flags.NONE) == 0

    def test_hidden_flag_set_via_hide(self):
        msg = SceneMessage(message="hi")
        assert msg.hidden == Flags.NONE
        msg.hide()
        assert msg.flags & Flags.HIDDEN
        assert bool(msg.hidden)

    def test_unhide_clears_hidden_flag(self):
        msg = SceneMessage(message="hi", flags=Flags.HIDDEN)
        assert msg.hidden
        msg.unhide()
        assert not msg.hidden
        assert msg.flags == Flags.NONE

    def test_hide_is_idempotent(self):
        msg = SceneMessage(message="hi")
        msg.hide()
        msg.hide()
        # Setting the same bit twice keeps the value identical.
        assert msg.flags == Flags.HIDDEN


# ---------------------------------------------------------------------------
# SceneMessage base class
# ---------------------------------------------------------------------------


class TestSceneMessageBase:
    def test_str_returns_message(self):
        m = SceneMessage(message="hello world")
        assert str(m) == "hello world"

    def test_int_returns_id(self):
        m = SceneMessage(message="x")
        assert int(m) == m.id

    def test_len_returns_message_length(self):
        m = SceneMessage(message="hello")
        assert len(m) == 5

    def test_iter_yields_characters(self):
        m = SceneMessage(message="ab")
        assert list(iter(m)) == ["a", "b"]

    def test_split_delegates_to_message(self):
        m = SceneMessage(message="a:b:c")
        assert m.split(":") == ["a", "b", "c"]

    def test_startswith_endswith_delegate_to_message(self):
        m = SceneMessage(message="hello world")
        assert m.startswith("hello")
        assert m.endswith("world")
        assert not m.startswith("world")

    def test_contains_message_in_other(self):
        m = SceneMessage(message="cat")
        # __contains__ is overridden to test self.message in other (reversed
        # semantics from the typical container usage).
        assert "the cat sat".__contains__  # sanity
        assert "the cat sat".__contains__ is not None
        # The dataclass override returns True when the message is contained
        # within `other`.
        assert m.__contains__("the cat sat") is True
        assert m.__contains__("dog only") is False

    def test_dict_returns_serialisable_payload(self):
        m = SceneMessage(message="hi", source="ai", flags=Flags.HIDDEN)
        d = m.to_dict()
        assert d["message"] == "hi"
        assert d["typ"] == "scene"
        assert d["source"] == "ai"
        assert d["flags"] == int(Flags.HIDDEN)
        assert d["rev"] == 0
        assert "id" in d
        assert "meta" not in d  # omitted when None

    def test_dict_includes_meta_when_set(self):
        m = SceneMessage(message="hi", meta={"agent": "narrator"})
        d = m.to_dict()
        assert d["meta"] == {"agent": "narrator"}

    def test_raw_returns_message_as_string(self):
        m = SceneMessage(message="hello")
        assert m.raw == "hello"

    def test_secondary_source_falls_back_to_source(self):
        m = SceneMessage(message="hi", source="ai")
        assert m.secondary_source == "ai"

    def test_set_source_populates_meta(self):
        m = SceneMessage(message="hi")
        m.set_source("narrator", "narrate_scene", topic="weather")
        assert m.meta == {
            "agent": "narrator",
            "function": "narrate_scene",
            "arguments": {"topic": "weather"},
        }
        assert m.source_agent == "narrator"
        assert m.source_function == "narrate_scene"
        assert m.source_arguments == {"topic": "weather"}

    def test_set_meta_merges_into_existing_meta(self):
        m = SceneMessage(message="hi")
        m.set_meta(a=1)
        m.set_meta(b=2)
        assert m.meta == {"a": 1, "b": 2}

    def test_source_helpers_default_when_meta_missing(self):
        m = SceneMessage(message="hi")
        assert m.source_agent is None
        assert m.source_function is None
        assert m.source_arguments == {}

    def test_meta_hash_changes_with_meta(self):
        m = SceneMessage(message="hi")
        h1 = m.meta_hash
        m.set_meta(x=1)
        h2 = m.meta_hash
        assert h1 != h2

    def test_fingerprint_is_stable_for_same_message(self):
        a = SceneMessage(message="same")
        b = SceneMessage(message="same")
        assert a.fingerprint == b.fingerprint
        assert len(a.fingerprint) <= 16

    def test_fingerprint_differs_for_different_messages(self):
        a = SceneMessage(message="alpha")
        b = SceneMessage(message="beta")
        assert a.fingerprint != b.fingerprint

    def test_as_format_movie_script_appends_newline(self):
        m = SceneMessage(message="hello\n\n")
        # rstrips trailing newlines then adds exactly one.
        assert m.as_format("movie_script") == "hello\n"
        assert m.as_format("ai_aware") == "hello\n"

    def test_as_format_narrative_strips_whitespace(self):
        m = SceneMessage(message="  hello  \n")
        assert m.as_format("narrative") == "hello"

    def test_as_format_unknown_returns_raw_message(self):
        m = SceneMessage(message="raw message")
        assert m.as_format("nonsense") == "raw message"


# ---------------------------------------------------------------------------
# CharacterMessage
# ---------------------------------------------------------------------------


class TestCharacterMessage:
    def test_character_name_extracts_prefix(self):
        m = CharacterMessage(message="Alice: Hello there!")
        assert m.character_name == "Alice"
        assert m.secondary_source == "Alice"

    def test_without_name_returns_dialogue_part(self):
        m = CharacterMessage(message="Alice: Hello there!")
        assert m.without_name == " Hello there!"

    def test_raw_strips_quotes_and_asterisks(self):
        m = CharacterMessage(message='Alice: "Hello" *waves*')
        # The raw property removes asterisks and quotes from the dialogue.
        assert m.raw == "Hello waves"

    def test_as_movie_script_uppercases_name(self):
        m = CharacterMessage(message="Alice: Hello")
        assert m.as_movie_script == "\nALICE\nHello\nEND-OF-LINE\n"

    def test_as_movie_script_handles_missing_colon_gracefully(self):
        m = CharacterMessage(message="just text without a colon")
        # When the message does not contain a colon, character_name returns
        # the entire message and the script falls back to using it whole.
        result = m.as_movie_script
        assert "END-OF-LINE" in result
        assert "JUST TEXT WITHOUT A COLON" in result

    def test_as_format_movie_script_returns_movie_script(self):
        m = CharacterMessage(message="Alice: Hello")
        assert m.as_format("movie_script") == m.as_movie_script
        assert m.as_format("ai_aware") == m.as_movie_script

    def test_as_format_narrative_returns_dialogue_only(self):
        m = CharacterMessage(message="Alice: Hello there")
        assert m.as_format("narrative") == "Hello there"

    def test_as_format_default_returns_full_message(self):
        m = CharacterMessage(message="Alice: Hello")
        assert m.as_format("chat") == "Alice: Hello"

    def test_dict_includes_optional_fields_when_set(self):
        m = CharacterMessage(
            message="Alice: hi",
            from_choice="choice-1",
            asset_id="asset-123",
            asset_type="avatar",
        )
        d = m.to_dict()
        assert d["from_choice"] == "choice-1"
        assert d["asset_id"] == "asset-123"
        assert d["asset_type"] == "avatar"

    def test_dict_omits_unset_optional_fields(self):
        m = CharacterMessage(message="Alice: hi")
        d = m.to_dict()
        assert "from_choice" not in d
        assert "asset_id" not in d
        assert "asset_type" not in d

    def test_default_source_is_ai(self):
        m = CharacterMessage(message="Alice: hi")
        assert m.source == "ai"
        assert m.typ == "character"


# ---------------------------------------------------------------------------
# NarratorMessage
# ---------------------------------------------------------------------------


class TestNarratorMessage:
    def test_default_typ_is_narrator(self):
        m = NarratorMessage(message="The sun rises.")
        assert m.typ == "narrator"
        assert m.source == "ai"

    def test_source_to_meta_paraphrase(self):
        m = NarratorMessage(message="x", source="paraphrase:original text")
        meta = m.source_to_meta()
        assert meta == {
            "agent": "narrator",
            "function": "paraphrase",
            "arguments": {"narration": "original text"},
        }

    def test_source_to_meta_narrate_character_entry(self):
        m = NarratorMessage(message="x", source="narrate_character_entry:Bob")
        meta = m.source_to_meta()
        assert meta["function"] == "narrate_character_entry"
        assert meta["arguments"] == {"character": "Bob"}

    def test_source_to_meta_narrate_query(self):
        m = NarratorMessage(message="x", source="narrate_query:What time is it?")
        meta = m.source_to_meta()
        assert meta["function"] == "narrate_query"
        assert meta["arguments"] == {"query": "What time is it?"}

    def test_source_to_meta_narrate_time_passage(self):
        m = NarratorMessage(
            message="x", source="narrate_time_passage:1h:1 hour later:they slept"
        )
        meta = m.source_to_meta()
        assert meta["function"] == "narrate_time_passage"
        assert meta["arguments"] == {
            "duration": "1h",
            "time_passed": "1 hour later",
            "narrative": "they slept",
        }

    def test_source_to_meta_progress_story(self):
        m = NarratorMessage(message="x", source="progress_story:advance plot")
        meta = m.source_to_meta()
        assert meta["function"] == "progress_story"
        assert meta["arguments"] == {"narrative_direction": "advance plot"}

    def test_source_to_meta_unknown_action_returns_empty_arguments(self):
        m = NarratorMessage(message="x", source="unknown_action:foo")
        meta = m.source_to_meta()
        assert meta["function"] == "unknown_action"
        assert meta["arguments"] == {}

    def test_migrate_source_to_meta_populates_meta(self):
        m = NarratorMessage(
            message="The sun rises.", source="paraphrase:earlier paraphrase"
        )
        assert m.meta is None
        m.migrate_source_to_meta()
        assert m.meta is not None
        assert m.meta["agent"] == "narrator"
        assert m.meta["function"] == "paraphrase"

    def test_migrate_source_to_meta_skips_when_meta_already_set(self):
        existing = {"agent": "narrator", "function": "preset", "arguments": {}}
        m = NarratorMessage(
            message="x", source="paraphrase:would clobber", meta=dict(existing)
        )
        m.migrate_source_to_meta()
        assert m.meta == existing

    def test_migrate_source_to_meta_handles_malformed_source(self):
        # narrate_time_passage requires three colon-separated parts; missing
        # parts should be caught by the migration helper and the meta should
        # remain unset rather than raising.
        m = NarratorMessage(message="x", source="narrate_time_passage:only one part")
        m.migrate_source_to_meta()
        assert m.meta is None

    def test_dict_includes_asset_fields(self):
        m = NarratorMessage(
            message="text", asset_id="img-1", asset_type="scene_illustration"
        )
        d = m.to_dict()
        assert d["asset_id"] == "img-1"
        assert d["asset_type"] == "scene_illustration"


# ---------------------------------------------------------------------------
# DirectorMessage
# ---------------------------------------------------------------------------


class TestDirectorMessage:
    def test_character_name_pulled_from_meta(self):
        m = DirectorMessage(
            message="be brave",
            meta={"agent": "director", "function": "x", "character": "Alice"},
        )
        assert m.character_name == "Alice"

    def test_character_name_none_when_meta_missing(self):
        m = DirectorMessage(message="be brave")
        assert m.character_name is None

    def test_instructions_returns_message(self):
        m = DirectorMessage(message="instructions go here")
        assert m.instructions == "instructions go here"

    def test_as_inner_monologue_replaces_pronouns(self):
        m = DirectorMessage(
            message="You should ready your sword and trust yourself",
            meta={
                "agent": "director",
                "function": "actor_instruction",
                "character": "Alice",
            },
        )
        result = m.as_inner_monologue
        assert "Alice thinks: I should" in result
        # word boundary replacement
        assert " i should " in result
        assert "myself" in result
        assert "my sword" in result
        assert "yourself" not in result
        assert "your" not in result

    def test_as_inner_monologue_without_character_returns_lowercase_instructions(self):
        m = DirectorMessage(message="You Stand Tall")
        # No character name -> just lowercases without prefix
        assert m.as_inner_monologue == "you stand tall"

    def test_as_story_progression_includes_character_and_instructions(self):
        m = DirectorMessage(
            message="charge ahead",
            meta={
                "agent": "director",
                "function": "actor_instruction",
                "character": "Bob",
            },
        )
        assert m.as_story_progression == "Bob's next action: charge ahead"

    def test_str_uses_chat_format(self):
        m = DirectorMessage(
            message="charge",
            meta={
                "agent": "director",
                "function": "actor_instruction",
                "character": "Bob",
            },
        )
        # Default format is chat -> "# {as_story_progression}"
        assert str(m) == "# Bob's next action: charge"

    def test_as_format_internal_monologue_chat(self):
        m = DirectorMessage(
            message="trust yourself",
            meta={
                "agent": "director",
                "function": "actor_instruction",
                "character": "Bob",
            },
        )
        result = m.as_format("chat", mode="internal_monologue")
        assert result.startswith("# ")
        assert "Bob thinks" in result

    def test_as_format_movie_script_default_mode(self):
        m = DirectorMessage(
            message="advance",
            meta={
                "agent": "director",
                "function": "actor_instruction",
                "character": "Bob",
            },
        )
        result = m.as_format("movie_script")
        assert result == "\n(Bob's next action: advance)\n"

    def test_as_format_returns_empty_for_blank_message(self):
        m = DirectorMessage(message="   ")
        assert m.as_format("chat") == ""
        assert m.as_format("movie_script") == ""

    def test_migrate_legacy_director_instructs_message(self):
        m = DirectorMessage(message="Director instructs Alice: be brave")
        m.migrate_message_to_meta()
        assert m.message == "be brave"
        assert m.source == "player"
        assert m.meta["agent"] == "director"
        assert m.meta["function"] == "actor_instruction"
        # The legacy migration stores the character under arguments rather
        # than at the top of meta, so character_name (which reads from
        # meta["character"]) does not pick it up. Verify both behaviours:
        assert m.meta["arguments"]["character"] == "Alice"
        assert m.character_name is None

    def test_character_name_reads_top_level_meta_key(self):
        # character_name pulls directly from meta["character"], not from the
        # nested arguments dict that set_source populates.
        m = DirectorMessage(
            message="x", meta={"agent": "director", "function": "y", "character": "Eve"}
        )
        assert m.character_name == "Eve"

    def test_migrate_backfills_subtype_for_user_direction(self):
        m = DirectorMessage(message="proceed", action="user_direction")
        assert m.subtype is None
        m.migrate_message_to_meta()
        assert m.subtype == "user_direction"

    def test_dict_includes_action_and_subtype_when_set(self):
        m = DirectorMessage(
            message="x", action="user_direction", subtype="user_direction"
        )
        d = m.to_dict()
        assert d["action"] == "user_direction"
        assert d["subtype"] == "user_direction"


# ---------------------------------------------------------------------------
# TimePassageMessage
# ---------------------------------------------------------------------------


class TestTimePassageMessage:
    def test_default_attrs(self):
        m = TimePassageMessage(message="A day later")
        assert m.typ == "time"
        assert m.source == "manual"
        assert m.ts == "PT0S"

    def test_dict_includes_ts(self):
        m = TimePassageMessage(message="A day later", ts="P1D")
        d = m.to_dict()
        assert d["ts"] == "P1D"
        assert d["typ"] == "time"


# ---------------------------------------------------------------------------
# ReinforcementMessage
# ---------------------------------------------------------------------------


class TestReinforcementMessage:
    def test_character_name_and_question_from_meta(self):
        m = ReinforcementMessage(
            message="They are loyal",
            meta={
                "agent": "world_state",
                "function": "update_reinforcement",
                "arguments": {"character": "Alice", "question": "are they loyal?"},
            },
        )
        assert m.character_name == "Alice"
        assert m.question == "are they loyal?"

    def test_character_name_default_when_meta_missing(self):
        m = ReinforcementMessage(message="x")
        assert m.character_name == "character"
        assert m.question == "question"

    def test_str_formats_internal_note(self):
        m = ReinforcementMessage(
            message="They are loyal",
            meta={
                "agent": "world_state",
                "function": "update_reinforcement",
                "arguments": {"character": "Alice", "question": "are they loyal?"},
            },
        )
        s = str(m)
        assert s.startswith("# Internal note for Alice - are they loyal?\n")
        assert s.endswith("They are loyal")

    def test_as_format_narrative_wraps_in_parens(self):
        m = ReinforcementMessage(
            message="They are loyal",
            meta={
                "agent": "world_state",
                "function": "update_reinforcement",
                "arguments": {"character": "Alice", "question": "are they loyal?"},
            },
        )
        # narrative format strips leading "# " and wraps in newlines/parens
        result = m.as_format("narrative")
        assert result.startswith("\n(")
        assert result.endswith(")\n")
        assert "Internal note for Alice" in result

    def test_as_format_default_just_pads_message(self):
        m = ReinforcementMessage(message="hello")
        assert m.as_format("chat") == "\nhello\n"

    def test_source_to_meta_populates_meta(self):
        m = ReinforcementMessage(
            message="They are loyal", source="are they loyal?:Alice"
        )
        m.source_to_meta()
        assert m.meta == {
            "agent": "world_state",
            "function": "update_reinforcement",
            "arguments": {"character": "Alice", "question": "are they loyal?"},
        }


# ---------------------------------------------------------------------------
# ContextInvestigationMessage
# ---------------------------------------------------------------------------


class TestContextInvestigationMessage:
    def test_title_for_visual_character_subtype(self):
        m = ContextInvestigationMessage(
            message="Alice wears a red cloak",
            sub_type="visual-character",
            meta={
                "agent": "x",
                "function": "y",
                "arguments": {"character": "Alice"},
            },
        )
        assert m.title == "Visual description of Alice in the current moment"

    def test_title_for_visual_scene_subtype(self):
        m = ContextInvestigationMessage(message="A field", sub_type="visual-scene")
        assert m.title == "Visual description of the current moment"

    def test_title_for_query_subtype(self):
        m = ContextInvestigationMessage(
            message="response",
            sub_type="query",
            meta={
                "agent": "x",
                "function": "y",
                "arguments": {"query": "Why is the sky blue?"},
            },
        )
        assert m.title == "Query: Why is the sky blue?"

    def test_title_default_when_unknown_subtype(self):
        m = ContextInvestigationMessage(message="x", sub_type="other")
        assert m.title == "Internal note"

    def test_str_combines_title_and_message(self):
        m = ContextInvestigationMessage(message="content", sub_type="visual-scene")
        assert str(m) == "# Visual description of the current moment: content"

    def test_as_format_narrative_strips_asterisks(self):
        m = ContextInvestigationMessage(message="con*tent*", sub_type="visual-scene")
        result = m.as_format("narrative")
        assert "*" not in result
        assert "Visual description of the current moment" in result

    def test_as_format_default_pads_with_newlines(self):
        m = ContextInvestigationMessage(message="content")
        assert m.as_format("chat") == "\ncontent\n"

    def test_dict_includes_sub_type_always(self):
        m = ContextInvestigationMessage(message="x", sub_type="visual-scene")
        d = m.to_dict()
        assert d["sub_type"] == "visual-scene"

    def test_dict_includes_assets_when_set(self):
        m = ContextInvestigationMessage(
            message="x",
            sub_type="visual-scene",
            asset_id="img-1",
            asset_type="scene_illustration",
        )
        d = m.to_dict()
        assert d["asset_id"] == "img-1"
        assert d["asset_type"] == "scene_illustration"
