from typing import TYPE_CHECKING
import traceback
import structlog
import talemate.instance as instance
import talemate.agents.tts.voice_library as voice_library
from talemate.agents.tts.schema import Voice
from talemate.util import random_color
from talemate.character import deactivate_character, set_voice
from talemate.status import LoadingStatus
from talemate.exceptions import GenerationCancelled
from talemate.agents.base import AgentAction, AgentActionConfig, set_processing
import talemate.game.focal as focal


__all__ = [
    "CharacterManagementMixin",
]

log = structlog.get_logger()

if TYPE_CHECKING:
    from talemate import Character, Scene
    from talemate.agents.tts import TTSAgent


class VoiceCandidate(Voice):
    used: bool = False


class CharacterManagementMixin:
    """
    Director agent mixin that provides functionality for automatically guiding
    the actors or the narrator during the scene progression.
    """

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["character_management"] = AgentAction(
            enabled=True,
            container=True,
            can_be_disabled=False,
            label="Character Management",
            icon="mdi-account",
            description="Configure how the director manages characters.",
            config={
                "assign_voice": AgentActionConfig(
                    type="bool",
                    label="Assign Voice (TTS)",
                    description="If enabled, the director is allowed to assign a text-to-speech voice when persisting a character.",
                    value=True,
                    title="Persisting Characters",
                ),
            },
        )

    # config property helpers

    @property
    def cm_assign_voice(self) -> bool:
        return self.actions["character_management"].config["assign_voice"].value

    @property
    def cm_should_assign_voice(self) -> bool:
        if not self.cm_assign_voice:
            return False

        tts_agent: "TTSAgent" = instance.get_agent("tts")
        if not tts_agent.enabled:
            return False

        if not tts_agent.ready_apis:
            return False

        return True

    # actions

    @set_processing
    async def persist_characters_from_worldstate(
        self, exclude: list[str] = None
    ) -> list["Character"]:
        created_characters = []

        for character_name in self.scene.world_state.characters.keys():
            if exclude and character_name.lower() in exclude:
                continue

            if character_name in self.scene.character_names:
                continue

            character = await self.persist_character(name=character_name)

            created_characters.append(character)

        self.scene.emit_status()

        return created_characters

    @set_processing
    async def persist_character(
        self,
        name: str,
        content: str = None,
        attributes: str = None,
        determine_name: bool = True,
        templates: list[str] = None,
        active: bool = True,
        narrate_entry: bool = False,
        narrate_entry_direction: str = "",
        augment_attributes: str = "",
        generate_attributes: bool = True,
        description: str = "",
        assign_voice: bool = True,
    ) -> "Character":
        world_state = instance.get_agent("world_state")
        creator = instance.get_agent("creator")
        narrator = instance.get_agent("narrator")
        memory = instance.get_agent("memory")
        scene: "Scene" = self.scene
        any_attribute_templates = False

        loading_status = LoadingStatus(max_steps=None, cancellable=True)

        # Start of character creation
        log.debug("persist_character", name=name)

        # Determine the character's name (or clarify if it's already set)
        if determine_name:
            loading_status("Determining character name")
            name = await creator.determine_character_name(name, instructions=content)
            log.debug("persist_character", adjusted_name=name)

        # Create the blank character
        character: "Character" = self.scene.Character(name=name)

        # Add the character to the scene
        character.color = random_color()
        actor = self.scene.Actor(
            character=character, agent=instance.get_agent("conversation")
        )
        await self.scene.add_actor(actor)

        try:
            # Apply any character generation templates
            if templates:
                loading_status("Applying character generation templates")
                templates = scene.world_state_manager.template_collection.collect_all(
                    templates
                )
                log.debug("persist_character", applying_templates=templates)
                await scene.world_state_manager.apply_templates(
                    templates.values(),
                    character_name=character.name,
                    information=content,
                )

                # if any of the templates are attribute templates, then we no longer need to
                # generate a character sheet
                any_attribute_templates = any(
                    template.template_type == "character_attribute"
                    for template in templates.values()
                )
                log.debug(
                    "persist_character", any_attribute_templates=any_attribute_templates
                )

                if (
                    any_attribute_templates
                    and augment_attributes
                    and generate_attributes
                ):
                    log.debug(
                        "persist_character", augmenting_attributes=augment_attributes
                    )
                    loading_status("Augmenting character attributes")
                    additional_attributes = await world_state.extract_character_sheet(
                        name=name,
                        text=content,
                        augmentation_instructions=augment_attributes,
                    )
                    character.base_attributes.update(additional_attributes)

            # Generate a character sheet if there are no attribute templates
            if not any_attribute_templates and generate_attributes:
                loading_status("Generating character sheet")
                log.debug("persist_character", extracting_character_sheet=True)
                if not attributes:
                    attributes = await world_state.extract_character_sheet(
                        name=name, text=content
                    )
                else:
                    attributes = world_state._parse_character_sheet(attributes)

                log.debug("persist_character", attributes=attributes)
                character.base_attributes = attributes

            # Generate a description for the character
            if not description:
                loading_status("Generating character description")
                description = await creator.determine_character_description(
                    character, information=content
                )
                character.description = description
                log.debug("persist_character", description=description)

            # Generate a dialogue instructions for the character
            loading_status("Generating acting instructions")
            dialogue_instructions = (
                await creator.determine_character_dialogue_instructions(
                    character, information=content
                )
            )
            character.dialogue_instructions = dialogue_instructions
            log.debug("persist_character", dialogue_instructions=dialogue_instructions)

            # Narrate the character's entry if the option is selected
            if active and narrate_entry:
                loading_status("Narrating character entry")
                is_present = await world_state.is_character_present(name)
                if not is_present:
                    await narrator.action_to_narration(
                        "narrate_character_entry",
                        emit_message=True,
                        character=character,
                        narrative_direction=narrate_entry_direction,
                    )

            if assign_voice:
                await self.assign_voice_to_character(character)

            # Deactivate the character if not active
            if not active:
                await deactivate_character(scene, character)

            # Commit the character's details to long term memory
            await character.commit_to_memory(memory)
            self.scene.emit_status()
            self.scene.world_state.emit()

            loading_status.done(
                message=f"{character.name} added to scene", status="success"
            )
            return character
        except GenerationCancelled:
            loading_status.done(message="Character creation cancelled", status="idle")
            await scene.remove_actor(actor)
        except Exception:
            loading_status.done(message="Character creation failed", status="error")
            await scene.remove_actor(actor)
            log.error("Error persisting character", error=traceback.format_exc())

    @set_processing
    async def assign_voice_to_character(
        self, character: "Character"
    ) -> list[focal.Call]:
        tts_agent: "TTSAgent" = instance.get_agent("tts")
        if not self.cm_should_assign_voice:
            log.debug("assign_voice_to_character", skip=True, reason="not enabled")
            return

        vl: voice_library.VoiceLibrary = voice_library.get_instance()

        ready_tts_apis = tts_agent.ready_apis

        voices = voice_library.voices_for_apis(ready_tts_apis, vl)

        if not voices:
            log.debug(
                "assign_voice_to_character", skip=True, reason="no voices available"
            )
            return

        voice_candidates = {
            voice.id: VoiceCandidate(**voice.model_dump()) for voice in voices
        }

        for scene_character in self.scene.all_characters:
            if scene_character.voice:
                voice_candidates[scene_character.voice.id].used = True

        async def assign_voice(voice_id: str):
            voice = vl.get_voice(voice_id)
            await set_voice(character, voice, auto=True)
            await self.log_action(
                f"Assigned voice `{voice.label}` to `{character.name}`",
                "Assigned voice",
                console_only=True,
            )
            

        focal_handler = focal.Focal(
            self.client,
            callbacks=[
                focal.Callback(
                    name="assign_voice",
                    arguments=[focal.Argument(name="voice_id", type="str")],
                    fn=assign_voice,
                ),
            ],
            max_calls=1,
            character=character,
            voices=list(voice_candidates.values()),
            scene=self.scene,
            narrator_voice=tts_agent.narrator_voice,
        )

        await focal_handler.request("director.cm-assign-voice")

        log.debug("assign_voice_to_character", calls=focal_handler.state.calls)

        return focal_handler.state.calls
