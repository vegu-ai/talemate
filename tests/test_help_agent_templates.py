"""Unit tests for `talemate.agents.help.templates`, the world state template
tools the help chat calls for every type except themes."""

import json
import os
import pathlib
import subprocess

import pytest

import talemate

import talemate.agents.help.storage as help_storage
import talemate.agents.help.templates as help_templates
import talemate.config.state as config_state
import talemate.world_state.templates as world_state_templates
from conftest import (
    MockClient,
    MockClientContext,
    MockScene,
    bootstrap_engine,
    bootstrap_scene,
    client_responses,
)
from talemate.agents.help import HelpAgent
from talemate.agents.help.websocket_handler import HelpWebsocketHandler
from talemate.config.schema import Config
from talemate.scene_tools import SCENE_TOOL_ACTIONS
from talemate.tale_mate import Actor, Character
from talemate.world_state.templates.base import (
    MODELS,
    TEMPLATE_PATH_TALEMATE,
    Collection,
    Group,
)
from talemate.world_state.templates.character import Attribute
from talemate.world_state.templates.state_reinforcement import StateReinforcement
from talemate.world_state.templates.visual import VISUAL_TYPES
from talemate.world_state.templates.theme import Theme, invalidate_theme_cache

SHIPPED_GROUP = "Talemate"
USER_GROUP = "My Templates"

DOCS_ROOT = pathlib.Path(talemate.__file__).parent.parent.parent / "docs"


class MockWebsocketHandler:
    """Stand-in for `WebsocketHandler` - the template pushes only need these."""

    def __init__(self, scene):
        self.scene = scene
        self.messages: list[dict] = []

    def queue_put(self, data: dict):
        self.messages.append(data)

    @property
    def actions(self) -> list[str]:
        return [message.get("action", message["type"]) for message in self.messages]

    def find(self, action: str) -> dict | None:
        for message in self.messages:
            if message.get("action", message["type"]) == action:
                return message
        return None


def template_id(template) -> str:
    return f"{template.group}__{template.uid}"


@pytest.fixture
def shipped_dir(template_dir) -> str:
    path = os.path.join(template_dir, "talemate")
    os.makedirs(path)
    return path


@pytest.fixture
def config(monkeypatch, tmp_path, template_dir, shipped_dir, isolate_signals) -> Config:
    """A throwaway app config plus a template directory of the test's own."""
    isolate_signals("config.changed", "config.changed.follow", "config.saved")

    original = config_state.CONFIG
    cfg = Config()
    cfg.dirty = False
    config_state.CONFIG = cfg
    monkeypatch.setattr(config_state, "CONFIG_FILE", tmp_path / "config.yaml")
    monkeypatch.setattr(world_state_templates, "TEMPLATE_PATH", template_dir)
    monkeypatch.setattr(help_templates, "TEMPLATE_PATH_TALEMATE", shipped_dir)
    invalidate_theme_cache()

    yield cfg

    config_state.CONFIG = original
    invalidate_theme_cache()


@pytest.fixture
def shipped_attribute() -> Attribute:
    return Attribute(name="Physical Traits", attribute="Physical Traits", locked=True)


@pytest.fixture
def user_attribute() -> Attribute:
    return Attribute(
        name="Fighting Style",
        attribute="Fighting Style",
        instructions="How they fight.",
    )


@pytest.fixture
def user_state() -> StateReinforcement:
    return StateReinforcement(name="Mood", query="What is their mood?")


@pytest.fixture
def scene(
    config,
    template_dir,
    shipped_dir,
    shipped_attribute,
    user_attribute,
    user_state,
) -> MockScene:
    """A scene whose collection holds a shipped and a user group."""
    shipped = Group(author="Talemate", name=SHIPPED_GROUP, description="")
    shipped.insert_template(shipped_attribute, save=False)
    shipped.path = os.path.join(shipped_dir, "talemate.yaml")
    shipped.save()

    user = Group(author="You", name=USER_GROUP, description="")
    user.insert_template(user_attribute, save=False)
    user.insert_template(user_state, save=False)
    user.save(template_dir)

    scene = MockScene()
    scene._world_state_templates = Collection(groups=[shipped, user])
    return scene


@pytest.fixture
def help_agent(tmp_path, monkeypatch, scene) -> HelpAgent:
    # focal reaches for the director agent to log its calls
    bootstrap_engine()
    monkeypatch.setattr(help_storage, "HELP_CHATS_DIR", tmp_path)
    monkeypatch.setattr(help_storage, "HELP_CHATS_FILE", tmp_path / "help.json")
    agent = HelpAgent(client=MockClient("test_client"))
    # these suites drive the write tools; the permission is off by default
    agent.actions["permissions"].config["allow_template_changes"].value = True
    agent.scene = scene
    return agent


@pytest.fixture
async def tracked_state(scene, user_state):
    """An NPC whose mood the `Mood` template already tracks, answered.

    `user_state` is switched to auto-create, which is the state a template is
    in once the user turns that on in the Templates tab.
    """
    # the apply path reads the scene off the world state agent, the way a
    # loaded scene binds it
    bootstrap_scene(scene)
    user_state.auto_create = True

    character = Character(name="Alice")
    scene.actors.append(Actor(character=character, agent=None))
    character.details["What is their mood?"] = "Cheerful."

    await scene.world_state.add_reinforcement(
        question="What is their mood?",
        character="Alice",
        insert="sequential",
        answer="Cheerful.",
    )

    return character


def _is_tracked(path: pathlib.Path) -> bool:
    """Whether git holds this file, i.e. whether Talemate ships it."""
    return (
        subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(path)],
            cwd=pathlib.Path(talemate.__file__).parent.parent.parent,
            capture_output=True,
        ).returncode
        == 0
    )


def created_template(scene, name: str):
    for group in scene._world_state_templates.groups:
        for template in group.templates.values():
            if template.name == name:
                return template
    raise AssertionError(f"no template named {name}")


class TestListTemplates:
    def test_lists_every_template_with_its_type_and_group(self, scene):
        listed = help_templates.list_templates(scene)

        assert {entry["name"] for entry in listed} == {
            "Physical Traits",
            "Fighting Style",
            "Mood",
        }
        assert {entry["group"] for entry in listed} == {SHIPPED_GROUP, USER_GROUP}
        assert {entry["template_type"] for entry in listed} == {
            "character_attribute",
            "state_reinforcement",
        }

    def test_filters_by_type(self, scene):
        listed = help_templates.list_templates(scene, "state_reinforcement")

        assert [entry["name"] for entry in listed] == ["Mood"]

    def test_marks_the_shipped_template_locked(self, scene):
        listed = {
            entry["name"]: entry for entry in help_templates.list_templates(scene)
        }

        assert "locked" in listed["Physical Traits"]
        assert "locked" not in listed["Fighting Style"]

    def test_says_so_when_there_are_none_of_a_type(self, scene):
        assert "No templates of type 'spices'" in help_templates.list_templates(
            scene, "spices"
        )

    def test_an_unknown_type_lists_the_valid_ones(self, scene):
        result = help_templates.list_templates(scene, "nonsense")

        assert "Unknown template type 'nonsense'" in result
        assert "character_attribute" in result
        # the same list the prompt renders, so a typo is not sent to a type
        # these tools refuse
        assert "theme" not in result


class TestReadTemplate:
    def test_returns_every_field(self, scene, user_attribute):
        payload = help_templates.read_template(scene, template_id(user_attribute))

        assert payload["name"] == "Fighting Style"
        assert payload["fields"]["instructions"] == "How they fight."
        assert payload["fields"]["supports_spice"] is False

    def test_hides_the_plumbing_fields(self, scene, user_attribute):
        payload = help_templates.read_template(scene, template_id(user_attribute))

        assert not set(payload["fields"]) & set(help_templates.HIDDEN_FIELDS)

    def test_resolves_a_template_by_name(self, scene, user_attribute):
        payload = help_templates.read_template(scene, "fighting style")

        assert payload["id"] == template_id(user_attribute)

    def test_unknown_template_says_where_to_look(self, scene):
        assert "list_templates" in help_templates.read_template(scene, "Nowhere")


class TestDescribeTemplateType:
    def test_names_the_required_fields_of_the_type(self):
        described = help_templates.describe_template_type("character_attribute")

        assert described["fields"]["attribute"]["required"] is True
        assert described["fields"]["supports_spice"]["default"] is False

    def test_carries_the_defaults_of_the_model(self):
        fields = help_templates.describe_template_type("state_reinforcement")["fields"]

        assert fields["interval"]["default"] == 10
        assert fields["insert"]["default"] == "sequential"

    def test_choices_come_from_the_models_own_type(self):
        fields = help_templates.describe_template_type("state_reinforcement")["fields"]

        assert fields["state_type"]["choices"] == [
            "character",
            "npc",
            "player",
            "world",
        ]

    def test_choices_of_an_untyped_field_come_from_its_authority(self):
        fields = help_templates.describe_template_type("scene_tool_shortcut")["fields"]

        assert fields["action_id"]["choices"] == [
            action.id for action in SCENE_TOOL_ACTIONS
        ]

    def test_a_nested_model_carries_its_own_fields(self):
        fields = help_templates.describe_template_type("writing_style")["fields"]
        phrases = fields["phrases"]

        assert phrases["type"] == "list of object"
        assert set(phrases["object_fields"]) == {
            "phrase",
            "instructions",
            "classification",
            "match_method",
            "active",
        }

    def test_a_nested_field_does_not_borrow_the_outer_description(self):
        """`instructions` means the writing style itself on the template and the
        fix for a phrase inside one - the outer note would misdescribe it."""
        fields = help_templates.describe_template_type("writing_style")["fields"]

        assert "description" not in fields["phrases"]["object_fields"]["instructions"]
        assert fields["instructions"]["description"]

    def test_choices_inside_a_list_are_reported(self):
        """`PromptFinalizer.flags` is a list of a Literal - the choices sit on
        the item, and a model that has to guess them burns a tool-call round."""
        fields = help_templates.describe_template_type("visual_finalizer")["fields"]
        flags = fields["finalizers"]["object_fields"]["flags"]

        assert flags["item_choices"] == ["case_sensitive", "dot_all", "multiline"]

    def test_the_visual_type_choices_are_the_ones_the_styles_carry(self):
        """The visualizer filters on STYLE for the general art style, and it is
        the value 6 of the shipped styles hold - VIS_TYPE has no such member."""
        fields = help_templates.describe_template_type("visual_style")["fields"]

        assert fields["visual_type"]["choices"] == list(VISUAL_TYPES)
        assert fields["visual_type"]["default"] == "STYLE"
        assert "STYLE" in fields["visual_type"]["choices"]
        assert "UNSPECIFIED" not in fields["visual_type"]["choices"]

    def test_priority_is_described(self):
        """It has a control in the Templates tab, so calling it 'not a field'
        would be false."""
        fields = help_templates.describe_template_type("character_attribute")["fields"]

        assert fields["priority"]["default"] == 1

    def test_the_plumbing_fields_are_not_described(self):
        fields = help_templates.describe_template_type("scene_type")["fields"]

        assert not set(fields) & set(help_templates.HIDDEN_FIELDS)

    def test_the_state_reinforcement_carries_the_auto_create_warning(self):
        described = help_templates.describe_template_type("state_reinforcement")

        assert "Templates tab" in described["auto_create_note"]

    def test_an_unknown_type_lists_the_valid_ones(self):
        result = help_templates.describe_template_type("colors")

        assert "Unknown template type 'colors'" in result
        assert "visual_style" in result


class TestTypeCoverage:
    """The prompt and the tools take their types from the registry, so a type
    the application gains without a line here would reach the LLM unexplained."""

    def test_every_registered_type_has_a_purpose(self):
        assert set(help_templates.TYPE_PURPOSE) == set(MODELS)

    def test_every_registered_type_names_a_documentation_page(self):
        assert set(help_templates.TYPE_DOCS) == set(MODELS)

    def test_every_named_documentation_page_exists(self):
        missing = [
            path
            for path in help_templates.TYPE_DOCS.values()
            if not (DOCS_ROOT / path).exists()
        ]

        assert missing == []

    def test_the_type_reference_covers_every_type_these_tools_write(self):
        """The prompt renders this as the valid values of `template_type`, and
        every tool that takes one refuses a theme. An unfiltered list still
        shows the themes that exist, which `TestThemesAreElsewhere` covers."""
        listed = {entry["type"] for entry in help_templates.type_reference()}

        assert listed == set(MODELS) - {"theme"}


class TestThemesAreElsewhere:
    def test_creating_a_theme_names_the_theme_tools(self, scene):
        result = help_templates.describe_template_type("theme")

        assert "create_theme" in result

    async def test_the_create_tool_refuses_a_theme(self, scene):
        result = await help_templates.create_template(
            scene,
            "theme",
            "Aurora",
            USER_GROUP,
            scene_loaded=False,
        )

        assert "list_themes" in result

    def test_reading_a_theme_names_the_theme_tools(self, scene, template_dir):
        group = scene._world_state_templates.groups[1]
        theme = Theme(name="Midnight", group=group.uid)
        group.insert_template(theme, save=False)

        result = help_templates.read_template(scene, template_id(theme))

        assert "read_theme" in result


class TestCreateTemplate:
    async def test_writes_the_fields_it_was_given(self, scene):
        result = await help_templates.create_template(
            scene,
            "character_detail",
            "Greatest Fear",
            USER_GROUP,
            fields={"detail": "What is their greatest fear?", "supports_spice": True},
            scene_loaded=False,
        )

        assert result["created"] is True
        template = created_template(scene, "Greatest Fear")
        assert template.detail == "What is their greatest fear?"
        assert template.supports_spice is True

    async def test_leaves_the_fields_it_was_not_given_at_their_defaults(self, scene):
        await help_templates.create_template(
            scene,
            "state_reinforcement",
            "Location",
            USER_GROUP,
            fields={"query": "Where are they?"},
            scene_loaded=False,
        )

        template = created_template(scene, "Location")
        assert template.interval == 10
        assert template.state_type == "npc"

    async def test_an_unknown_group_is_created(self, scene, template_dir):
        result = await help_templates.create_template(
            scene,
            "scene_type",
            "Interrogation",
            "Story Beats",
            fields={"description": "A tense questioning."},
            scene_loaded=False,
        )

        assert result["group_created"] is True
        assert os.path.exists(os.path.join(template_dir, "story-beats.yaml"))

    async def test_the_shipped_group_takes_no_new_templates(self, scene):
        result = await help_templates.create_template(
            scene,
            "character_attribute",
            "Height",
            SHIPPED_GROUP,
            fields={"attribute": "Height"},
            scene_loaded=False,
        )

        assert "ships with Talemate" in result
        assert len(scene._world_state_templates.groups[0].templates) == 1

    async def test_a_duplicate_name_in_the_group_is_refused(self, scene):
        result = await help_templates.create_template(
            scene,
            "character_attribute",
            "Fighting Style",
            USER_GROUP,
            fields={"attribute": "Fighting Style"},
            scene_loaded=False,
        )

        assert "already holds a character_attribute template" in result

    async def test_an_unknown_field_names_the_valid_ones(self, scene):
        result = await help_templates.create_template(
            scene,
            "character_attribute",
            "Height",
            USER_GROUP,
            fields={"attribute": "Height", "colors": {}},
            scene_loaded=False,
        )

        assert "'colors' is not a field of a character_attribute template" in result
        assert "supports_spice" in result

    async def test_a_value_outside_the_authority_is_refused(self, scene):
        result = await help_templates.create_template(
            scene,
            "scene_tool_shortcut",
            "Look",
            USER_GROUP,
            fields={
                "action_id": "narrator.stare",
                "label": "Look",
                "icon": "mdi-eye",
            },
            scene_loaded=False,
        )

        assert "is not a valid action_id" in result
        assert "narrator.look_at_scene" in result

    async def test_a_value_the_model_rejects_is_reported(self, scene):
        result = await help_templates.create_template(
            scene,
            "scene_tool_shortcut",
            "Look",
            USER_GROUP,
            fields={
                "action_id": "narrator.look_at_scene",
                "label": "Look",
                "icon": "eye",
            },
            scene_loaded=False,
        )

        assert "Invalid value for 'icon'" in result

    async def test_a_missing_required_field_is_reported(self, scene):
        result = await help_templates.create_template(
            scene,
            "character_attribute",
            "Height",
            USER_GROUP,
            scene_loaded=False,
        )

        assert "Invalid value for 'attribute'" in result

    async def test_an_invalid_name_is_refused(self, scene):
        result = await help_templates.create_template(
            scene,
            "character_attribute",
            "Height/Weight",
            USER_GROUP,
            fields={"attribute": "Height"},
            scene_loaded=False,
        )

        assert "letters, digits, spaces and underscores" in result

    async def test_the_name_is_not_taken_from_the_fields(self, scene):
        result = await help_templates.create_template(
            scene,
            "character_attribute",
            "Height",
            USER_GROUP,
            fields={"attribute": "Height", "name": "Something else"},
            scene_loaded=False,
        )

        assert "'name' argument" in result


class TestEveryWritableType:
    """One create per type, asserting what it stored - the shapes with lists,
    nested objects and choice fields are only exercised here."""

    @pytest.mark.parametrize(
        "template_type,fields,check",
        [
            (
                "character_detail",
                {"detail": "What do they fear most?"},
                lambda t: t.detail == "What do they fear most?",
            ),
            (
                "spices",
                {
                    "spices": ["make it rain", "add a stranger"],
                    "instructions": "{spice}",
                },
                lambda t: t.spices == ["make it rain", "add a stranger"],
            ),
            (
                "writing_style",
                {
                    "instructions": "Terse, concrete prose.",
                    "phrases": [
                        {"phrase": "suddenly", "instructions": "Cut the adverb."}
                    ],
                },
                lambda t: t.phrases[0].phrase == "suddenly"
                and t.phrases[0].classification == "unwanted",
            ),
            (
                "agent_persona",
                {"instructions": "Speak plainly.", "initial_chat_message": "Hi."},
                lambda t: t.initial_chat_message == "Hi.",
            ),
            (
                "visual_style",
                {"positive_keywords": ["oil painting"], "visual_type": "STYLE"},
                lambda t: t.visual_type == "STYLE"
                and t.positive_keywords == ["oil painting"],
            ),
            (
                "visual_finalizer",
                {
                    "finalizers": [
                        {
                            "mode": "REGEX",
                            "match": "\\bblurry\\b",
                            "replace": "",
                            "flags": ["case_sensitive"],
                        }
                    ]
                },
                lambda t: t.finalizers[0].mode == "REGEX"
                and t.finalizers[0].flags == ["case_sensitive"],
            ),
            (
                "scene_type",
                {
                    "description": "A tense questioning.",
                    "instructions": "Keep it terse.",
                },
                lambda t: t.description == "A tense questioning.",
            ),
        ],
    )
    async def test_creates_and_stores_the_fields(
        self, scene, template_type, fields, check
    ):
        result = await help_templates.create_template(
            scene,
            template_type,
            "E2E Shape",
            USER_GROUP,
            fields=fields,
            scene_loaded=False,
        )

        assert result["created"] is True, result
        assert check(created_template(scene, "E2E Shape"))

    async def test_the_visual_type_the_shipped_styles_use_is_accepted(self, scene):
        """It is the model default and what six shipped styles carry, but it is
        not a `VIS_TYPE` member - reading a style and writing it back has to work."""
        result = await help_templates.create_template(
            scene,
            "visual_style",
            "Painterly",
            USER_GROUP,
            fields={"visual_type": "STYLE"},
            scene_loaded=False,
        )

        assert result["created"] is True
        assert created_template(scene, "Painterly").visual_type == "STYLE"

    async def test_a_visual_type_outside_the_set_is_refused(self, scene):
        result = await help_templates.create_template(
            scene,
            "visual_style",
            "Painterly",
            USER_GROUP,
            fields={"visual_type": "UNSPECIFIED"},
            scene_loaded=False,
        )

        assert "Invalid value for 'visual_type'" in result


class TestShippedGroups:
    def test_every_group_talemate_ships_is_read_only_to_the_agent(self):
        """`is_shipped` is a directory check, so a shipped group whose file sits
        outside `templates/world-state/talemate/` would be writable."""
        shipped_root = pathlib.Path(TEMPLATE_PATH_TALEMATE).resolve()
        template_root = shipped_root.parent

        stray = [
            path.name for path in template_root.glob("*.yaml") if _is_tracked(path)
        ]

        assert stray == [], (
            "these ship with Talemate but sit outside the shipped directory, "
            f"so the help agent may rewrite them: {stray}"
        )

    def test_the_visual_styles_group_reads_as_shipped(self):
        group = Group.load(
            str(pathlib.Path(TEMPLATE_PATH_TALEMATE) / "visual-styles.yaml")
        )

        assert help_templates.is_shipped(group)


class TestAutoCreate:
    """Saving a state reinforcement with auto_create applies it to the loaded
    scene's characters, which is a scene write - not the help agent's to make."""

    async def test_refused_while_a_scene_is_loaded(self, scene):
        result = await help_templates.create_template(
            scene,
            "state_reinforcement",
            "Mood Tracker",
            USER_GROUP,
            fields={"query": "What is their mood?", "auto_create": True},
            scene_loaded=True,
        )

        assert "Templates tab" in result
        with pytest.raises(AssertionError):
            created_template(scene, "Mood Tracker")

    async def test_written_when_no_scene_is_loaded(self, scene):
        result = await help_templates.create_template(
            scene,
            "state_reinforcement",
            "Mood Tracker",
            USER_GROUP,
            fields={"query": "What is their mood?", "auto_create": True},
            scene_loaded=False,
        )

        assert result["created"] is True
        assert created_template(scene, "Mood Tracker").auto_create is True

    async def test_an_update_that_turns_it_on_is_refused_too(self, scene, user_state):
        result = await help_templates.update_template(
            scene, template_id(user_state), {"auto_create": True}, scene_loaded=True
        )

        assert "Templates tab" in result
        assert user_state.auto_create is False

    async def test_a_patch_to_a_template_that_already_auto_creates_is_refused(
        self, tracked_state, scene, user_state
    ):
        """The flag does not have to be in the call: every save of a template
        that carries it re-applies it, and a re-apply blanks what it tracked."""
        result = await help_templates.update_template(
            scene, template_id(user_state), {"interval": 5}, scene_loaded=True
        )

        assert "Templates tab" in result
        assert user_state.interval == 10
        assert scene.world_state.reinforce[0].answer == "Cheerful."
        assert tracked_state.get_detail("What is their mood?") == "Cheerful."

    async def test_the_re_apply_this_guards_against_is_real(
        self, tracked_state, scene, user_state
    ):
        """The oracle for the test above: the save path the tool would have
        reached does blank the answer, so the refusal is load-bearing."""
        await scene.world_state_manager.save_template(user_state)

        assert scene.world_state.reinforce[0].answer == ""
        # an empty detail is dropped rather than stored, so it is gone entirely
        assert tracked_state.get_detail("What is their mood?") is None

    async def test_turning_auto_create_off_is_allowed(
        self, tracked_state, scene, user_state
    ):
        result = await help_templates.update_template(
            scene, template_id(user_state), {"auto_create": False}, scene_loaded=True
        )

        assert result["updated"] is True
        assert created_template(scene, "Mood").auto_create is False

    async def test_a_world_state_reinforcement_is_not_refused(self, scene):
        """`auto_apply_template_state_reinforcement` has no branch for `world`,
        so it reaches no character and writes no scene."""
        result = await help_templates.create_template(
            scene,
            "state_reinforcement",
            "Weather",
            USER_GROUP,
            fields={
                "query": "What is the weather?",
                "state_type": "world",
                "auto_create": True,
            },
            scene_loaded=True,
        )

        assert result["created"] is True
        assert created_template(scene, "Weather").auto_create is True


class TestUpdateTemplate:
    async def test_changes_only_what_it_was_given(self, scene, user_attribute):
        result = await help_templates.update_template(
            scene,
            template_id(user_attribute),
            {"instructions": "One paragraph."},
            scene_loaded=False,
        )

        assert result["changes"]["instructions"]["previous"] == "How they fight."
        template = created_template(scene, "Fighting Style")
        assert template.instructions == "One paragraph."
        assert template.attribute == "Fighting Style"

    async def test_says_so_when_nothing_changes(self, scene, user_attribute):
        result = await help_templates.update_template(
            scene,
            template_id(user_attribute),
            {"instructions": "How they fight."},
            scene_loaded=False,
        )

        assert "already holds those values" in result

    async def test_a_locked_template_is_refused_with_the_copy_route(
        self, scene, shipped_attribute
    ):
        result = await help_templates.update_template(
            scene,
            template_id(shipped_attribute),
            {"instructions": "Changed."},
            scene_loaded=False,
        )

        assert "create_template" in result
        assert shipped_attribute.instructions is None

    async def test_a_value_the_model_rejects_leaves_the_template_alone(
        self, scene, user_state
    ):
        result = await help_templates.update_template(
            scene,
            template_id(user_state),
            {"state_type": "monster"},
            scene_loaded=False,
        )

        assert "Invalid value for 'state_type'" in result
        assert user_state.state_type == "npc"

    async def test_an_empty_field_set_asks_for_one(self, scene, user_attribute):
        result = await help_templates.update_template(
            scene,
            template_id(user_attribute),
            {},
            scene_loaded=False,
        )

        assert "Name the fields to change" in result

    async def test_a_rename_is_validated(self, scene, user_attribute):
        result = await help_templates.update_template(
            scene,
            template_id(user_attribute),
            {"name": "Fighting/Style"},
            scene_loaded=False,
        )

        assert "letters, digits, spaces and underscores" in result

    async def test_a_rename_onto_a_sibling_is_refused(self, scene, user_attribute):
        """Two templates of one type sharing a name in one group make both
        unreachable by name afterwards."""
        await help_templates.create_template(
            scene,
            "character_attribute",
            "Height",
            USER_GROUP,
            fields={"attribute": "Height"},
            scene_loaded=False,
        )

        result = await help_templates.update_template(
            scene,
            template_id(user_attribute),
            {"name": "Height"},
            scene_loaded=False,
        )

        assert "already holds a character_attribute template" in result
        assert created_template(scene, "Fighting Style").name == "Fighting Style"

    async def test_a_rename_that_only_changes_case_is_allowed(
        self, scene, user_attribute
    ):
        """The template being renamed is not its own collision."""
        result = await help_templates.update_template(
            scene,
            template_id(user_attribute),
            {"name": "Fighting style"},
            scene_loaded=False,
        )

        assert result["updated"] is True

    async def test_priority_can_be_set(self, scene, user_attribute):
        result = await help_templates.update_template(
            scene,
            template_id(user_attribute),
            {"priority": 3},
            scene_loaded=False,
        )

        assert result["updated"] is True
        assert created_template(scene, "Fighting Style").priority == 3


class TestUnsavedEditRefusals:
    async def test_create_is_refused_while_the_templates_tab_is_dirty(self, scene):
        result = await help_templates.create_template(
            scene,
            "character_attribute",
            "Height",
            USER_GROUP,
            fields={"attribute": "Height"},
            templates_dirty=True,
            scene_loaded=False,
        )

        assert "Templates tab has an unsaved template edit" in result
        with pytest.raises(AssertionError):
            created_template(scene, "Height")

    async def test_update_is_refused_while_the_templates_tab_is_dirty(
        self, scene, user_attribute
    ):
        result = await help_templates.update_template(
            scene,
            template_id(user_attribute),
            {"instructions": "Changed."},
            templates_dirty=True,
            scene_loaded=False,
        )

        assert "Templates tab has an unsaved template edit" in result
        assert user_attribute.instructions == "How they fight."


class TestSceneStateIsReadAtCallTime:
    """The scene the write would reach is whichever one is bound when the call
    lands, not the one that was bound when the round was built - a scene can be
    loaded while the client is generating, and `init_scene` rebinds every
    agent's scene when it is."""

    def _create(self, help_agent):
        callbacks = {
            callback.name: callback
            for callback in help_agent._chat_template_callbacks()
        }
        return callbacks["create_template"]

    async def test_a_scene_loaded_after_the_round_was_built_is_seen(
        self, help_agent, scene
    ):
        help_agent.scene = MockScene()
        create = self._create(help_agent)

        # the round is built with no scene; the user opens one while the
        # client generates
        help_agent.scene = scene
        scene.name = "Infinity Quest"

        result = await create.fn(
            "state_reinforcement",
            "Mood Tracker",
            USER_GROUP,
            {"query": "What is their mood?", "auto_create": True},
        )

        assert "Templates tab" in result
        with pytest.raises(AssertionError):
            created_template(scene, "Mood Tracker")

    async def test_a_scene_released_after_the_round_was_built_is_seen(
        self, help_agent, scene
    ):
        scene.name = "Infinity Quest"
        create = self._create(help_agent)

        scene.name = ""

        result = await create.fn(
            "state_reinforcement",
            "Mood Tracker",
            USER_GROUP,
            {"query": "What is their mood?", "auto_create": True},
        )

        assert result["created"] is True


class TestChatIntegration:
    async def test_a_write_through_the_chat_loop_creates_the_template(
        self, help_agent, scene
    ):
        chat = help_agent.chat_create()
        call_block = json.dumps(
            {
                "function": "create_template",
                "arguments": {
                    "template_type": "character_detail",
                    "name": "Greatest Fear",
                    "group": USER_GROUP,
                    "fields": {"detail": "What is their greatest fear?"},
                },
            }
        )

        async with MockClientContext():
            responses = client_responses.get()
            responses.append(f"```json\n{call_block}\n```")
            responses.append("Created Greatest Fear in My Templates.")

            await help_agent.chat_send(chat.id, "Make me a greatest fear template")

        results = [
            message
            for message in help_agent.chat_get(chat.id).messages
            if message.type == "doc_result"
        ]
        assert len(results) == 1
        assert results[0].name == "create_template"
        assert results[0].result["created"] is True
        assert created_template(scene, "Greatest Fear").detail == (
            "What is their greatest fear?"
        )

    async def test_the_write_is_refused_when_the_snapshot_reports_a_dirty_tab(
        self, help_agent, scene
    ):
        chat = help_agent.chat_create()
        call_block = json.dumps(
            {
                "function": "create_template",
                "arguments": {
                    "template_type": "character_detail",
                    "name": "Greatest Fear",
                    "group": USER_GROUP,
                    "fields": {"detail": "What is their greatest fear?"},
                },
            }
        )

        async with MockClientContext():
            responses = client_responses.get()
            responses.append(f"```json\n{call_block}\n```")
            responses.append("Save your template edit first.")

            await help_agent.chat_send(
                chat.id,
                "Make me a greatest fear template",
                ux_snapshot={"templates_view": {"dirty": True}},
            )

        results = [
            message
            for message in help_agent.chat_get(chat.id).messages
            if message.type == "doc_result"
        ]
        assert "unsaved template edit" in results[0].result

    async def test_a_template_write_only_pushes_the_template_list(self, scene, config):
        """A theme write also pushes `app_config`, which carries the colors the
        app repaints with; nothing else a template write changes rides on it."""
        handler = MockWebsocketHandler(scene)
        plugin = HelpWebsocketHandler(handler)

        *_, on_templates_changed = plugin._make_generation_callbacks()
        await on_templates_changed(None)

        assert handler.actions == ["templates"]
        assert handler.find("templates")["data"]["managed"]["groups"]


def test_the_prompt_sends_applying_and_deleting_to_the_templates_tab():
    """Neither is a tool - the only thing that can tell the agent where they
    happen is the prompt."""
    prompt = (
        pathlib.Path(talemate.__file__).parent
        / "prompts"
        / "templates"
        / "help"
        / "chat.jinja2"
    )
    text = prompt.read_text()

    assert "CANNOT apply, install or delete one" in text
    assert "Templates tab" in text
