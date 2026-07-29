"""Unit tests for talemate.load.character_card pure parsing helpers and pydantic models.

Covers:
- Pydantic models: defaults, validation, computed methods
- Format detection: identify_import_spec
- Spec-driven extraction: _extract_scene_name_from_spec,
  _extract_dialogue_examples_from_metadata, _extract_icon_asset_from_character_card
- character_from_chara_data: card-to-character conversion (V0/V1/V2/V3 paths)
- load_character_from_json / load_from_image_metadata: file-driven entry points
- _generate_unique_filename: collision handling
- _parse_characters_from_greeting_text: name parsing and fallbacks

LLM-driven, async, and image-asset-saving paths in the module are intentionally
excluded — they require a fully bootstrapped engine and are exercised through
the higher-level integration tests.
"""

from __future__ import annotations

import base64
import json

import pydantic
import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from talemate import Character
from talemate.agents.base import DynamicInstruction
from talemate.exceptions import UnknownDataSpec
from talemate.load.character_card import (
    CharacterBook,
    CharacterBookEntry,
    CharacterBookMeta,
    CharacterCardAnalysis,
    CharacterCardImportOptions,
    ImportSpec,
    PlayerCharacterImport,
    PlayerCharacterTemplate,
    RelevantCharacterInfo,
    _extract_character_data_from_file,
    _extract_dialogue_examples_from_metadata,
    _extract_icon_asset_from_character_card,
    _extract_scene_name_from_spec,
    _generate_unique_filename,
    _parse_characters_from_greeting_text,
    character_from_chara_data,
    identify_import_spec,
    load_character_from_image,
    load_character_from_json,
    load_from_image_metadata,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _v3_card(data: dict | None = None, top: dict | None = None) -> dict:
    """Build a minimal chara_card_v3 dict with optional overrides."""
    base = {"spec": "chara_card_v3", "data": {"name": "V3 Hero"}}
    if data:
        base["data"].update(data)
    if top:
        base.update(top)
    return base


def _v2_card(data: dict | None = None) -> dict:
    base = {"spec": "chara_card_v2", "data": {"name": "V2 Hero"}}
    if data:
        base["data"].update(data)
    return base


def _v1_card(extra: dict | None = None) -> dict:
    base = {"spec": "chara_card_v1", "name": "V1 Hero", "first_mes": "Hello!"}
    if extra:
        base.update(extra)
    return base


def _v0_card(extra: dict | None = None) -> dict:
    """V0 has no spec field but has first_mes at top-level."""
    base = {"name": "V0 Hero", "first_mes": "Greetings."}
    if extra:
        base.update(extra)
    return base


def _make_png_with_chara_chunk(path, payload: dict, *, chunk_keyword: str = "chara"):
    """Create a 1x1 PNG with a tEXt chunk containing base64-encoded JSON.

    chunk_keyword should be 'chara' (V1/V2) or 'ccv3' (V3 spec preferred chunk).
    """
    img = Image.new("RGB", (1, 1), color=(255, 255, 255))
    encoded = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    info = PngInfo()
    info.add_text(chunk_keyword, encoded)
    img.save(path, format="PNG", pnginfo=info)


# ---------------------------------------------------------------------------
# Lightweight scene stub for _parse_characters_from_greeting_text
# ---------------------------------------------------------------------------


class _SceneStub:
    """Minimal stand-in: _parse_characters_from_greeting_text only touches
    scene.character_data (a name -> Character mapping)."""

    def __init__(self, characters: list[Character]):
        self.character_data = {c.name: c for c in characters}


# ===========================================================================
# Pydantic model tests
# ===========================================================================


class TestRelevantCharacterInfo:
    def test_defaults_are_all_none(self):
        info = RelevantCharacterInfo()
        assert info.scene is None
        assert info.scenario is None
        assert info.character_info is None

    def test_to_dynamic_instructions_empty_returns_empty_list(self):
        info = RelevantCharacterInfo()
        assert info.to_dynamic_instructions() == []

    def test_to_dynamic_instructions_orders_scenario_then_info_then_scene(self):
        info = RelevantCharacterInfo(
            scene=DynamicInstruction(title="SCENE", content="greeting"),
            scenario=DynamicInstruction(title="SCENARIO", content="card"),
            character_info=DynamicInstruction(title="CHARACTER INFO", content="book"),
        )
        result = info.to_dynamic_instructions()
        assert [d.title for d in result] == ["SCENARIO", "CHARACTER INFO", "SCENE"]

    def test_to_dynamic_instructions_filters_each_flag_independently(self):
        info = RelevantCharacterInfo(
            scene=DynamicInstruction(title="SCENE", content="g"),
            scenario=DynamicInstruction(title="SCENARIO", content="s"),
            character_info=DynamicInstruction(title="CHARACTER INFO", content="i"),
        )
        # scenario excluded
        assert [d.title for d in info.to_dynamic_instructions(scenario=False)] == [
            "CHARACTER INFO",
            "SCENE",
        ]
        # character_info excluded
        assert [
            d.title for d in info.to_dynamic_instructions(character_info=False)
        ] == ["SCENARIO", "SCENE"]
        # scene excluded
        assert [d.title for d in info.to_dynamic_instructions(scene=False)] == [
            "SCENARIO",
            "CHARACTER INFO",
        ]
        # all excluded
        assert (
            info.to_dynamic_instructions(
                scenario=False, character_info=False, scene=False
            )
            == []
        )


class TestCharacterBookEntryDefaults:
    def test_required_fields_must_be_set(self):
        with pytest.raises(pydantic.ValidationError) as err:
            CharacterBookEntry(content="no keys")
        assert err.value.errors()[0]["loc"] == ("keys",)

        with pytest.raises(pydantic.ValidationError) as err:
            CharacterBookEntry(keys=["k"])
        assert err.value.errors()[0]["loc"] == ("content",)

    def test_defaults_match_spec(self):
        entry = CharacterBookEntry(keys=["k"], content="c")
        assert entry.extensions == {}
        assert entry.enabled is True
        assert entry.insertion_order == 0
        assert entry.case_sensitive is False
        assert entry.name is None
        assert entry.priority is None
        assert entry.id is None
        assert entry.comment is None
        assert entry.selective is False
        assert entry.secondary_keys == []
        assert entry.constant is False
        assert entry.position is None


class TestCharacterBookDefaults:
    def test_defaults_match_spec(self):
        book = CharacterBook()
        assert book.name is None
        assert book.description is None
        assert book.scan_depth is None
        assert book.token_budget is None
        assert book.recursive_scanning is False
        assert book.extensions == {}
        assert book.entries == []


class TestCharacterBookMeta:
    def test_keys_required(self):
        with pytest.raises(pydantic.ValidationError):
            CharacterBookMeta()

    def test_defaults(self):
        meta = CharacterBookMeta(keys=["a"])
        assert meta.character_book_name == ""
        assert meta.insertion_order == 0
        assert meta.case_sensitive is False
        assert meta.entry_name is None
        assert meta.priority is None
        assert meta.selective is False
        assert meta.secondary_keys == []
        assert meta.constant is False
        assert meta.position is None
        assert meta.extensions == {}


class TestPlayerCharacterModels:
    def test_template_requires_name(self):
        with pytest.raises(pydantic.ValidationError):
            PlayerCharacterTemplate()

    def test_template_default_description(self):
        t = PlayerCharacterTemplate(name="Alice")
        assert t.description == ""

    def test_player_character_import_requires_both_fields(self):
        with pytest.raises(pydantic.ValidationError):
            PlayerCharacterImport(name="Alice")
        with pytest.raises(pydantic.ValidationError):
            PlayerCharacterImport(scene_path="x")
        # both works
        p = PlayerCharacterImport(scene_path="scenes/foo", name="Alice")
        assert p.scene_path == "scenes/foo"
        assert p.name == "Alice"


class TestCharacterCardImportOptions:
    def test_defaults(self):
        opts = CharacterCardImportOptions()
        assert opts.import_all_characters is False
        assert opts.import_character_book is True
        assert opts.import_character_book_meta is True
        assert opts.import_alternate_greetings is True
        assert opts.generate_episode_titles is True
        assert opts.setup_shared_context is False
        assert opts.use_asset_as_reference is True
        assert opts.selected_character_names == []
        assert opts.player_character_template is None
        assert opts.player_character_existing is None
        assert opts.player_character_import is None
        assert opts.writing_style_template is None
        assert opts._pending_asset_transfers == []

    def test_validator_rejects_template_and_existing_combo(self):
        with pytest.raises(pydantic.ValidationError) as err:
            CharacterCardImportOptions(
                player_character_template=PlayerCharacterTemplate(name="A"),
                player_character_existing="B",
            )
        assert "Only one player character option" in str(err.value)

    def test_validator_rejects_template_and_import_combo(self):
        with pytest.raises(pydantic.ValidationError):
            CharacterCardImportOptions(
                player_character_template=PlayerCharacterTemplate(name="A"),
                player_character_import=PlayerCharacterImport(scene_path="x", name="A"),
            )

    def test_validator_rejects_existing_and_import_combo(self):
        with pytest.raises(pydantic.ValidationError):
            CharacterCardImportOptions(
                player_character_existing="A",
                player_character_import=PlayerCharacterImport(scene_path="x", name="B"),
            )

    def test_single_player_option_allowed(self):
        opts = CharacterCardImportOptions(
            player_character_template=PlayerCharacterTemplate(name="A")
        )
        assert opts.player_character_template.name == "A"

    def test_pending_asset_transfers_is_private_and_isolated_per_instance(self):
        a = CharacterCardImportOptions()
        b = CharacterCardImportOptions()
        a._pending_asset_transfers.append("x")
        # private attr default_factory must give each instance its own list
        assert b._pending_asset_transfers == []


class TestCharacterCardAnalysis:
    def test_required_field_and_defaults(self):
        with pytest.raises(pydantic.ValidationError):
            CharacterCardAnalysis()

        a = CharacterCardAnalysis(spec_version="chara_card_v2")
        assert a.spec_version == "chara_card_v2"
        assert a.character_book_entry_count == 0
        assert a.alternate_greetings_count == 0
        assert a.detected_character_names == []
        assert a.card_name is None
        assert a.icon_asset_data_url is None


class TestImportSpecEnum:
    def test_values_match_string_form(self):
        assert ImportSpec.talemate.value == "talemate"
        assert ImportSpec.talemate_complete.value == "talemate_complete"
        assert ImportSpec.chara_card_v0.value == "chara_card_v0"
        assert ImportSpec.chara_card_v1.value == "chara_card_v1"
        assert ImportSpec.chara_card_v2.value == "chara_card_v2"
        assert ImportSpec.chara_card_v3.value == "chara_card_v3"

    def test_is_str_enum(self):
        # Used as string in CharacterCardAnalysis.spec_version
        assert ImportSpec.chara_card_v2 == "chara_card_v2"


# ===========================================================================
# identify_import_spec
# ===========================================================================


class TestIdentifyImportSpec:
    def test_v3_by_explicit_spec(self):
        assert (
            identify_import_spec({"spec": "chara_card_v3"}) == ImportSpec.chara_card_v3
        )

    def test_v2_by_explicit_spec(self):
        assert (
            identify_import_spec({"spec": "chara_card_v2"}) == ImportSpec.chara_card_v2
        )

    def test_v1_by_explicit_spec(self):
        assert (
            identify_import_spec({"spec": "chara_card_v1"}) == ImportSpec.chara_card_v1
        )

    def test_v0_inferred_from_top_level_first_mes(self):
        assert identify_import_spec({"first_mes": "hi"}) == ImportSpec.chara_card_v0

    def test_v0_takes_precedence_over_data_first_mes(self):
        # Top-level first_mes with no spec is treated as v0 even if
        # data.first_mes is present.
        spec = identify_import_spec({"first_mes": "top", "data": {"first_mes": "x"}})
        assert spec == ImportSpec.chara_card_v0

    def test_v3_fallback_when_only_data_first_mes_set(self):
        # No spec, no top-level first_mes, but data.first_mes present
        spec = identify_import_spec({"data": {"first_mes": "hi"}})
        assert spec == ImportSpec.chara_card_v3

    def test_unknown_falls_back_to_talemate(self):
        # Missing first_mes anywhere is treated as a Talemate scene
        assert identify_import_spec({"some_key": "value"}) == ImportSpec.talemate

    def test_explicit_spec_takes_precedence_over_first_mes(self):
        # Even with first_mes at top level, explicit v2 spec wins
        assert (
            identify_import_spec({"spec": "chara_card_v2", "first_mes": "hi"})
            == ImportSpec.chara_card_v2
        )

    def test_non_dict_raises_value_error(self):
        with pytest.raises(ValueError, match="expected dictionary"):
            identify_import_spec("not a dict")
        with pytest.raises(ValueError, match="expected dictionary"):
            identify_import_spec(None)
        with pytest.raises(ValueError, match="expected dictionary"):
            identify_import_spec([1, 2, 3])


# ===========================================================================
# _extract_scene_name_from_spec
# ===========================================================================


class TestExtractSceneNameFromSpec:
    def test_v3_uses_data_name(self):
        assert _extract_scene_name_from_spec(_v3_card({"name": "Hero"})) == "Hero"

    def test_v2_uses_data_name(self):
        assert _extract_scene_name_from_spec(_v2_card({"name": "Hero"})) == "Hero"

    def test_v1_uses_top_level_name(self):
        assert _extract_scene_name_from_spec(_v1_card()) == "V1 Hero"

    def test_v0_uses_top_level_name(self):
        assert _extract_scene_name_from_spec(_v0_card()) == "V0 Hero"

    def test_v3_without_name_returns_none(self):
        # remove default name
        card = {"spec": "chara_card_v3", "data": {}}
        assert _extract_scene_name_from_spec(card) is None

    def test_v3_with_empty_name_returns_none(self):
        card = _v3_card({"name": ""})
        assert _extract_scene_name_from_spec(card) is None

    def test_returns_none_for_none_or_non_dict(self):
        assert _extract_scene_name_from_spec(None) is None
        assert _extract_scene_name_from_spec("string") is None
        assert _extract_scene_name_from_spec(42) is None

    def test_returns_none_for_empty_dict(self):
        # empty dict -> identify_import_spec returns talemate -> no name extracted
        assert _extract_scene_name_from_spec({}) is None


# ===========================================================================
# _extract_dialogue_examples_from_metadata
# ===========================================================================


class TestExtractDialogueExamples:
    def test_v3_reads_data_mes_example(self):
        card = _v3_card({"mes_example": "v3 dialog"})
        assert _extract_dialogue_examples_from_metadata(card) == "v3 dialog"

    def test_v2_reads_data_mes_example(self):
        card = _v2_card({"mes_example": "v2 dialog"})
        assert _extract_dialogue_examples_from_metadata(card) == "v2 dialog"

    def test_v1_reads_top_level_mes_example(self):
        card = _v1_card({"mes_example": "v1 dialog"})
        assert _extract_dialogue_examples_from_metadata(card) == "v1 dialog"

    def test_v0_reads_top_level_mes_example(self):
        card = _v0_card({"mes_example": "v0 dialog"})
        assert _extract_dialogue_examples_from_metadata(card) == "v0 dialog"

    def test_returns_empty_when_missing(self):
        # v2 without mes_example
        assert _extract_dialogue_examples_from_metadata(_v2_card()) == ""
        # v0 without mes_example
        assert _extract_dialogue_examples_from_metadata(_v0_card()) == ""

    def test_returns_empty_for_none_or_falsy(self):
        assert _extract_dialogue_examples_from_metadata(None) == ""
        assert _extract_dialogue_examples_from_metadata({}) == ""


# ===========================================================================
# _extract_icon_asset_from_character_card
# ===========================================================================


class TestExtractIconAsset:
    def test_prefers_main_icon_over_others(self):
        card = _v3_card(
            {
                "assets": [
                    {
                        "type": "icon",
                        "uri": "data:image/png;base64,b3RoZXI=",
                        "name": "other",
                    },
                    {
                        "type": "icon",
                        "uri": "data:image/png;base64,bWFpbg==",
                        "name": "main",
                    },
                ]
            }
        )
        assert (
            _extract_icon_asset_from_character_card(card)
            == "data:image/png;base64,bWFpbg=="
        )

    def test_falls_back_to_first_icon_when_no_main(self):
        card = _v3_card(
            {
                "assets": [
                    {
                        "type": "icon",
                        "uri": "data:image/png;base64,Zmlyc3Q=",
                        "name": "alt1",
                    },
                    {
                        "type": "icon",
                        "uri": "data:image/png;base64,c2Vjb25k",
                        "name": "alt2",
                    },
                ]
            }
        )
        assert (
            _extract_icon_asset_from_character_card(card)
            == "data:image/png;base64,Zmlyc3Q="
        )

    def test_skips_non_icon_assets(self):
        card = _v3_card(
            {
                "assets": [
                    {
                        "type": "background",
                        "uri": "data:image/png;base64,YmFja2dyb3VuZA==",
                        "name": "main",
                    },
                ]
            }
        )
        assert _extract_icon_asset_from_character_card(card) is None

    def test_skips_non_data_url_icons(self):
        card = _v3_card(
            {
                "assets": [
                    {
                        "type": "icon",
                        "uri": "https://example.com/icon.png",
                        "name": "main",
                    },
                ]
            }
        )
        assert _extract_icon_asset_from_character_card(card) is None

    def test_skips_non_dict_asset_entries(self):
        card = _v3_card(
            {
                "assets": [
                    "not a dict",
                    {
                        "type": "icon",
                        "uri": "data:image/png;base64,b2s=",
                        "name": "main",
                    },
                ]
            }
        )
        assert (
            _extract_icon_asset_from_character_card(card)
            == "data:image/png;base64,b2s="
        )

    def test_returns_none_for_no_assets_field(self):
        assert _extract_icon_asset_from_character_card(_v3_card()) is None

    def test_returns_none_for_assets_not_list(self):
        card = _v3_card({"assets": {"not": "a list"}})
        assert _extract_icon_asset_from_character_card(card) is None

    def test_returns_none_for_none_or_non_dict(self):
        assert _extract_icon_asset_from_character_card(None) is None
        assert _extract_icon_asset_from_character_card("string") is None
        assert _extract_icon_asset_from_character_card([]) is None

    def test_v0_top_level_assets_supported(self):
        # When there's no 'data' field, function falls back to top-level
        card = {
            "name": "X",
            "assets": [
                {
                    "type": "icon",
                    "uri": "data:image/jpeg;base64,dG9w",
                    "name": "main",
                }
            ],
        }
        assert (
            _extract_icon_asset_from_character_card(card)
            == "data:image/jpeg;base64,dG9w"
        )

    def test_v2_card_without_assets_field_returns_none(self):
        # V2 cards do not have the assets field
        card = _v2_card({"description": "no assets here"})
        assert _extract_icon_asset_from_character_card(card) is None


# ===========================================================================
# character_from_chara_data
# ===========================================================================


class TestCharacterFromCharaData:
    def test_minimal_data_yields_unknown_character_with_defaults(self):
        c = character_from_chara_data({})
        assert c.name == "UNKNOWN"
        assert c.description == ""
        assert c.greeting_text == ""
        assert c.example_dialogue == []

    def test_basic_fields_are_copied(self):
        data = {
            "name": "Alice",
            "description": "A heroine.",
            "first_mes": "Hello there!",
            "color": "#abcdef",
        }
        c = character_from_chara_data(data)
        assert c.name == "Alice"
        assert c.description == "A heroine."
        assert c.greeting_text == "Hello there!"
        assert c.color == "#abcdef"

    def test_scenario_appended_to_description(self):
        data = {
            "name": "Alice",
            "description": "Background.",
            "scenario": "She is in a forest.",
        }
        c = character_from_chara_data(data)
        assert c.description == "Background.\nShe is in a forest."

    def test_scenario_only_still_appended_to_blank_description(self):
        # When description missing but scenario present, character.description
        # starts empty, scenario is appended after a newline
        c = character_from_chara_data({"name": "X", "scenario": "alone"})
        assert c.description == "\nalone"

    def test_char_placeholder_replaced_in_string_fields(self):
        data = {
            "name": "Bob",
            "description": "{{char}} is brave.",
            "first_mes": "Hi, I'm {{char}}.",
        }
        c = character_from_chara_data(data)
        assert c.description == "Bob is brave."
        assert c.greeting_text == "Hi, I'm Bob."

    def test_char_placeholder_replacement_uses_unknown_when_no_name(self):
        # Name defaults to UNKNOWN, so {{char}} -> 'UNKNOWN'
        data = {"description": "{{char}} stands."}
        c = character_from_chara_data(data)
        assert c.description == "UNKNOWN stands."

    def test_mes_example_split_on_start_marker(self):
        data = {
            "name": "Alice",
            "mes_example": "<START>\nAlice: Hi!\nUser: Hello.\n<START>\nAlice: Bye.\n",
        }
        c = character_from_chara_data(data)
        # first segment before the leading <START> is empty/whitespace, skipped
        # second segment: 'Alice: Hi!' and 'User: Hello.'
        # third segment: 'Alice: Bye.'
        assert "Alice: Hi!" in c.example_dialogue
        assert "User: Hello." in c.example_dialogue
        assert "Alice: Bye." in c.example_dialogue
        # blank lines should not be present
        assert all(line for line in c.example_dialogue)

    def test_mes_example_handles_crlf_line_endings(self):
        data = {
            "name": "Alice",
            "mes_example": "<START>\r\nAlice: Hi!\r\nUser: Hello.\r\n",
        }
        c = character_from_chara_data(data)
        assert "Alice: Hi!" in c.example_dialogue
        assert "User: Hello." in c.example_dialogue

    def test_mes_example_empty_string_yields_no_examples(self):
        data = {"name": "Alice", "mes_example": ""}
        c = character_from_chara_data(data)
        assert c.example_dialogue == []

    def test_mes_example_replaces_char_placeholder(self):
        data = {
            "name": "Bob",
            "mes_example": "<START>\n{{char}}: Hi!\n",
        }
        c = character_from_chara_data(data)
        assert "Bob: Hi!" in c.example_dialogue

    def test_mes_example_replaces_smart_quotes(self):
        data = {
            "name": "Alice",
            "mes_example": "<START>\nAlice: “Hi there.” She waves. ‘Really.’\n",
        }
        c = character_from_chara_data(data)
        assert c.example_dialogue == [
            "Alice: \"Hi there.\" She waves. 'Really.'",
        ]

    def test_gender_field_persists_to_base_attributes(self):
        # 'gender' on Character is a read-only @property backed by
        # base_attributes; the loader writes to base_attributes so the
        # value round-trips through the property.
        c = character_from_chara_data({"name": "X", "gender": "female"})
        assert c.base_attributes["gender"] == "female"
        assert c.gender == "female"

    def test_non_string_fields_are_left_untouched_during_char_substitution(self):
        # Branch: data[key] is not a string -> .replace() is skipped.
        # Numeric/list/dict values must round-trip without crashing.
        data = {
            "name": "Alice",
            "description": "Hi from {{char}}.",
            "age": 30,
            "tags": ["one", "two"],
            "extras": {"k": "v"},
        }
        c = character_from_chara_data(data)
        # description (string) was substituted
        assert c.description == "Hi from Alice."
        # non-string fields are not touched (and should not crash)
        assert data["age"] == 30
        assert data["tags"] == ["one", "two"]
        assert data["extras"] == {"k": "v"}


# ===========================================================================
# load_character_from_json
# ===========================================================================


class TestLoadCharacterFromJSON:
    def test_loads_v2_card_using_data_section(self, tmp_path):
        card = _v2_card(
            {
                "name": "V2 Alice",
                "description": "From V2 data.",
                "first_mes": "V2 hi",
            }
        )
        f = tmp_path / "card.json"
        f.write_text(json.dumps(card))
        c = load_character_from_json(str(f))
        assert isinstance(c, Character)
        assert c.name == "V2 Alice"
        assert c.description == "From V2 data."
        assert c.greeting_text == "V2 hi"

    def test_loads_v3_card_using_data_section(self, tmp_path):
        card = _v3_card(
            {
                "name": "V3 Alice",
                "description": "From V3 data.",
                "first_mes": "V3 hi",
            }
        )
        f = tmp_path / "card.json"
        f.write_text(json.dumps(card))
        c = load_character_from_json(str(f))
        assert c.name == "V3 Alice"
        assert c.greeting_text == "V3 hi"

    def test_loads_v1_card_from_top_level(self, tmp_path):
        card = _v1_card({"description": "A V1 card."})
        f = tmp_path / "card.json"
        f.write_text(json.dumps(card))
        c = load_character_from_json(str(f))
        assert c.name == "V1 Hero"
        assert c.description == "A V1 card."

    def test_v0_card_loads_from_top_level(self, tmp_path):
        # V0 cards have no spec field but expose first_mes at top level —
        # `identify_import_spec` recognises them, and the loader now
        # treats V0 the same as V1 (top-level fields, no `data` wrapper).
        f = tmp_path / "card.json"
        f.write_text(json.dumps(_v0_card()))
        c = load_character_from_json(str(f))
        assert c.name == "V0 Hero"
        assert c.greeting_text == "Greetings."

    def test_talemate_scene_raises_unknown_data_spec(self, tmp_path):
        # Random JSON without first_mes is identified as 'talemate' which
        # the loader does not handle.
        f = tmp_path / "scene.json"
        f.write_text(json.dumps({"name": "scene", "history": []}))
        with pytest.raises(UnknownDataSpec):
            load_character_from_json(str(f))

    def test_invalid_json_raises_decode_error(self, tmp_path):
        f = tmp_path / "broken.json"
        f.write_text("{ this is not json")
        with pytest.raises(json.JSONDecodeError):
            load_character_from_json(str(f))


# ===========================================================================
# load_from_image_metadata / load_character_from_image
# ===========================================================================


class TestLoadFromImageMetadata:
    def test_v2_png_with_chara_chunk(self, tmp_path):
        card = _v2_card(
            {
                "name": "Image V2",
                "description": "Embedded V2",
                "first_mes": "Greetings!",
            }
        )
        img_path = tmp_path / "card.png"
        _make_png_with_chara_chunk(img_path, card, chunk_keyword="chara")

        char = load_from_image_metadata(str(img_path), "png")
        assert char.name == "Image V2"
        assert char.description == "Embedded V2"
        assert char.greeting_text == "Greetings!"

    def test_v3_png_with_ccv3_chunk(self, tmp_path):
        card = _v3_card(
            {
                "name": "Image V3",
                "description": "Embedded V3",
                "first_mes": "V3 hi",
            }
        )
        img_path = tmp_path / "card_v3.png"
        _make_png_with_chara_chunk(img_path, card, chunk_keyword="ccv3")

        char = load_from_image_metadata(str(img_path), "png")
        assert char.name == "Image V3"
        assert char.greeting_text == "V3 hi"

    def test_v0_png_uses_top_level(self, tmp_path):
        # V0 cards have no spec; load_from_image_metadata leaves data at top
        # level and passes it to character_from_chara_data directly.
        card = _v0_card({"description": "old style"})
        img_path = tmp_path / "v0.png"
        _make_png_with_chara_chunk(img_path, card, chunk_keyword="chara")

        char = load_from_image_metadata(str(img_path), "png")
        assert char.name == "V0 Hero"
        assert char.description == "old style"
        assert char.greeting_text == "Greetings."

    def test_load_character_from_image_v2(self, tmp_path):
        card = _v2_card({"name": "V2 Img Char", "first_mes": "yo"})
        img_path = tmp_path / "v2.png"
        _make_png_with_chara_chunk(img_path, card, chunk_keyword="chara")

        char = load_character_from_image(str(img_path), "png")
        assert char.name == "V2 Img Char"
        assert char.greeting_text == "yo"

    def test_load_character_from_image_v0_raises_unknown_data_spec(self, tmp_path):
        # load_character_from_image only handles v0/v1/v2/v3; v0 IS handled
        # via the chara_card_v1/v0 branch using top-level data.
        # But unhandled (e.g. talemate) data still raises UnknownDataSpec.
        # Confirm the v0 branch works first, then test talemate.
        v0_card = _v0_card({"description": "old"})
        img_path = tmp_path / "v0.png"
        _make_png_with_chara_chunk(img_path, v0_card, chunk_keyword="chara")
        char = load_character_from_image(str(img_path), "png")
        assert char.name == "V0 Hero"

        # Talemate-shaped data (no first_mes at any level) should raise
        talemate_data = {"name": "scene", "history": []}
        img_path2 = tmp_path / "talemate.png"
        _make_png_with_chara_chunk(img_path2, talemate_data, chunk_keyword="chara")
        with pytest.raises(UnknownDataSpec):
            load_character_from_image(str(img_path2), "png")


# ===========================================================================
# _extract_character_data_from_file
# ===========================================================================


class TestExtractCharacterDataFromFile:
    def test_json_v2_extracts_character_book_and_alternate_greetings(self, tmp_path):
        card = _v2_card(
            {
                "name": "JSON V2",
                "first_mes": "Hi",
                "alternate_greetings": ["alt1", "alt2"],
                "character_book": {
                    "name": "Lore",
                    "entries": [
                        {"keys": ["Alice"], "content": "Alice info."},
                    ],
                },
            }
        )
        f = tmp_path / "v2.json"
        f.write_text(json.dumps(card))

        char, book, alts, is_image, raw = _extract_character_data_from_file(
            str(f), ".json"
        )
        assert isinstance(char, Character)
        assert char.name == "JSON V2"
        assert is_image is False
        assert book == card["data"]["character_book"]
        assert alts == ["alt1", "alt2"]
        assert raw == card

    def test_json_v1_returns_no_character_book_or_alternate_greetings(self, tmp_path):
        # V1 cards don't have data.character_book or alternate_greetings;
        # those fields stay None / [].
        card = _v1_card({"description": "v1 desc"})
        f = tmp_path / "v1.json"
        f.write_text(json.dumps(card))

        char, book, alts, is_image, raw = _extract_character_data_from_file(
            str(f), ".json"
        )
        assert char.name == "V1 Hero"
        assert book is None
        assert alts == []
        assert is_image is False
        assert raw == card

    def test_image_v2_extracts_character_book_and_alternate_greetings(self, tmp_path):
        card = _v2_card(
            {
                "name": "Img V2",
                "first_mes": "hi",
                "alternate_greetings": ["g1"],
                "character_book": {
                    "name": "Lore",
                    "entries": [{"keys": ["x"], "content": "y"}],
                },
            }
        )
        img = tmp_path / "card.png"
        _make_png_with_chara_chunk(img, card, chunk_keyword="chara")

        char, book, alts, is_image, raw = _extract_character_data_from_file(
            str(img), ".png"
        )
        assert char.name == "Img V2"
        assert is_image is True
        assert book == card["data"]["character_book"]
        assert alts == ["g1"]
        assert raw == card

    def test_image_v3_extracts_via_ccv3_chunk(self, tmp_path):
        card = _v3_card(
            {
                "name": "Img V3",
                "first_mes": "v3 hi",
                "alternate_greetings": ["a", "b", "c"],
            }
        )
        img = tmp_path / "v3.png"
        _make_png_with_chara_chunk(img, card, chunk_keyword="ccv3")

        char, book, alts, is_image, raw = _extract_character_data_from_file(
            str(img), ".png"
        )
        assert char.name == "Img V3"
        assert is_image is True
        assert book is None
        assert alts == ["a", "b", "c"]

    def test_image_with_no_chara_chunk_raises_value_error(self, tmp_path):
        # A PNG without a 'chara' or 'ccv3' tEXt chunk yields False from
        # extract_metadata, which fails the isinstance(metadata, dict) check
        # and raises a user-friendly ValueError.
        plain = tmp_path / "no_metadata.png"
        Image.new("RGB", (1, 1)).save(plain, format="PNG")

        with pytest.raises(ValueError, match="does not contain valid character card"):
            _extract_character_data_from_file(str(plain), ".png")


# ===========================================================================
# _generate_unique_filename
# ===========================================================================


class TestGenerateUniqueFilename:
    def test_returns_input_when_file_does_not_exist(self, tmp_path):
        assert _generate_unique_filename("scene.json", tmp_path) == "scene.json"

    def test_appends_uid_when_file_exists(self, tmp_path):
        existing = tmp_path / "scene.json"
        existing.write_text("{}")
        result = _generate_unique_filename("scene.json", tmp_path)
        assert result != "scene.json"
        assert result.startswith("scene-")
        assert result.endswith(".json")
        # uuid hex is 8 chars: 'scene-XXXXXXXX.json'
        assert len(result) == len("scene-XXXXXXXX.json")

    def test_preserves_extension(self, tmp_path):
        existing = tmp_path / "initial.png"
        existing.write_text("x")
        result = _generate_unique_filename("initial.png", tmp_path)
        assert result.endswith(".png")
        assert result.startswith("initial-")

    def test_handles_no_extension(self, tmp_path):
        existing = tmp_path / "noext"
        existing.write_text("x")
        result = _generate_unique_filename("noext", tmp_path)
        # splitext returns ('noext', '') so result ends with the empty ext
        assert result.startswith("noext-")
        assert "." not in result  # no extension preserved


# ===========================================================================
# _parse_characters_from_greeting_text
# ===========================================================================


class TestParseCharactersFromGreetingText:
    def test_matches_name_colon_pattern_case_insensitive(self):
        scene = _SceneStub(
            [Character(name="Alice"), Character(name="Bob"), Character(name="Carol")]
        )
        result = _parse_characters_from_greeting_text("alice: Hello!\nbob: Hi.", scene)
        # original casing from character_data is preserved
        assert result == ["Alice", "Bob"]

    def test_dedupes_repeated_names(self):
        scene = _SceneStub([Character(name="Alice"), Character(name="Bob")])
        result = _parse_characters_from_greeting_text(
            "Alice: Hi.\nAlice: Hello again.\nBob: Hey.", scene
        )
        assert result == ["Alice", "Bob"]

    def test_falls_back_to_substring_match_for_npcs(self):
        # No 'name:' patterns -> falls back to substring search in NPCs
        scene = _SceneStub(
            [
                Character(name="Alice", is_player=True),
                Character(name="Bob"),
                Character(name="Carol"),
            ]
        )
        result = _parse_characters_from_greeting_text(
            "Bob walks into the room. He glances at Carol.", scene
        )
        assert "Bob" in result
        assert "Carol" in result
        # Player must not be picked up by NPC fallback
        assert "Alice" not in result

    def test_final_fallback_returns_first_two_npcs_when_no_match(self):
        # No name: patterns, and no NPC names appear in greeting
        scene = _SceneStub(
            [
                Character(name="Player", is_player=True),
                Character(name="NPC1"),
                Character(name="NPC2"),
                Character(name="NPC3"),
            ]
        )
        result = _parse_characters_from_greeting_text(
            "The wind howls through empty trees.", scene
        )
        # Final fallback: first two NPCs (in insertion order)
        assert result == ["NPC1", "NPC2"]

    def test_player_only_scene_with_no_match_returns_empty(self):
        scene = _SceneStub([Character(name="Player", is_player=True)])
        result = _parse_characters_from_greeting_text("nothing here.", scene)
        assert result == []

    def test_empty_greeting_text_returns_at_most_two_npcs(self):
        # No matches anywhere -> final fallback to first 2 NPCs
        scene = _SceneStub(
            [
                Character(name="A"),
                Character(name="B"),
                Character(name="C"),
            ]
        )
        result = _parse_characters_from_greeting_text("", scene)
        assert result == ["A", "B"]
