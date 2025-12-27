from typing import TYPE_CHECKING
import structlog
from talemate.agents.base import (
    set_processing,
)

import talemate.game.focal as focal
from talemate.scene_message import (
    CharacterMessage,
    TimePassageMessage,
    NarratorMessage,
)
from talemate.scene.schema import ScenePhase, SceneType
from talemate.scene.intent import set_scene_phase
from talemate.world_state.manager import WorldStateManager
from talemate.world_state.templates.scene import SceneType as TemplateSceneType
import talemate.agents.director.auto_direct_nodes  # noqa: F401
from talemate.world_state.templates.base import TypedCollection
from talemate.agents.base import AgentAction

if TYPE_CHECKING:
    from talemate.tale_mate import Character, Scene

log = structlog.get_logger("talemate.agents.conversation.direct")


# talemate.emit.async_signals.register(
# )


class AutoDirectMixin:
    """
    Director agent mixin for automatic scene direction.
    """

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        # DEPRECATED: AutoDirectMixin is deprecated, config removed
        pass

    # config property helpers
    # DEPRECATED: AutoDirectMixin is deprecated, using static values

    @property
    def auto_direct_enabled(self) -> bool:
        # DEPRECATED: Always returns False as AutoDirectMixin is deprecated
        return False

    @property
    def auto_direct_max_auto_turns(self) -> int:
        # DEPRECATED: Static value
        return 3

    @property
    def auto_direct_max_idle_turns(self) -> int:
        # DEPRECATED: Static value
        return 5

    @property
    def auto_direct_max_repeat_turns(self) -> int:
        # DEPRECATED: Static value
        return 1

    @property
    def auto_direct_instruct_actors(self) -> bool:
        # DEPRECATED: Static value
        return False

    @property
    def auto_direct_instruct_narrator(self) -> bool:
        # DEPRECATED: Static value
        return False

    @property
    def auto_direct_instruct_frequency(self) -> int:
        # DEPRECATED: Static value
        return 5

    @property
    def auto_direct_evaluate_scene_intention(self) -> int:
        # DEPRECATED: Static value
        return 0

    @property
    def auto_direct_instruct_any(self) -> bool:
        """
        Will check whether actor or narrator instructions are enabled.

        For narrator instructions to be enabled instruct_narrator needs to be enabled as well.

        Returns:
            bool: True if either actor or narrator instructions are enabled.
        """

        return self.auto_direct_instruct_actors or self.auto_direct_instruct_narrator

    # helpers

    def auto_direct_is_due_for_instruction(self, actor_name: str) -> bool:
        """
        Check if the actor is due for instruction.
        """

        if self.auto_direct_instruct_frequency == 1:
            return True

        messages_since_last_instruction = 0

        def count_messages(message):
            nonlocal messages_since_last_instruction
            if message.typ in ["character", "narrator"]:
                messages_since_last_instruction += 1

        last_instruction = self.scene.last_message_of_type(
            "director",
            character_name=actor_name,
            max_iterations=25,
            on_iterate=count_messages,
        )

        log.debug(
            "auto_direct_is_due_for_instruction",
            messages_since_last_instruction=messages_since_last_instruction,
            last_instruction=last_instruction.id if last_instruction else None,
        )

        if not last_instruction:
            return True

        return messages_since_last_instruction >= self.auto_direct_instruct_frequency

    def auto_direct_candidates(self) -> list["Character"]:
        """
        Returns a list of characters who are valid candidates to speak next.
        based on the max_idle_turns, max_repeat_turns, and the most recent character.
        """

        scene: "Scene" = self.scene

        most_recent_character = None
        repeat_count = 0
        last_player_turn = None
        consecutive_auto_turns = 0
        candidates = {}
        active_charcters = list(scene.characters)
        active_character_names = [character.name for character in active_charcters]
        instruct_narrator = self.auto_direct_instruct_narrator

        BACKLOG_LIMIT = 50

        player_character_active = scene.player_character_exists

        # check the last BACKLOG_LIMIT entries in the scene history and collect into
        # a dictionary of character names and the number of turns since they last spoke.

        len_history = len(scene.history) - 1
        num = 0
        for idx in range(len_history, -1, -1):
            message = scene.history[idx]
            turns = len_history - idx

            num += 1

            if num > BACKLOG_LIMIT:
                break

            if isinstance(message, TimePassageMessage):
                break

            if not isinstance(message, (CharacterMessage, NarratorMessage)):
                continue

            # if character message but character is not in the active characters list then skip
            if (
                isinstance(message, CharacterMessage)
                and message.character_name not in active_character_names
            ):
                continue

            if isinstance(message, NarratorMessage):
                if not instruct_narrator:
                    continue
                character = scene.narrator_character_object
            else:
                character = scene.get_character(message.character_name)

            if not character:
                continue

            if character.is_player and last_player_turn is None:
                last_player_turn = turns
            elif not character.is_player and last_player_turn is None:
                consecutive_auto_turns += 1

            if not most_recent_character:
                most_recent_character = character
                repeat_count += 1
            elif character == most_recent_character:
                repeat_count += 1

            if character.name not in candidates:
                candidates[character.name] = turns

        # add any characters that have not spoken yet
        for character in active_charcters:
            if character.name not in candidates:
                candidates[character.name] = 0

        # explicitly add narrator if enabled and not already in candidates
        if instruct_narrator and scene.narrator_character_object:
            narrator = scene.narrator_character_object
            if narrator.name not in candidates:
                candidates[narrator.name] = 0

        log.debug(
            f"auto_direct_candidates: {candidates}",
            most_recent_character=most_recent_character,
            repeat_count=repeat_count,
            last_player_turn=last_player_turn,
            consecutive_auto_turns=consecutive_auto_turns,
        )

        if not most_recent_character:
            log.debug("auto_direct_candidates: No most recent character found.")
            return list(scene.characters)

        # if player has not spoken in a while then they are favored
        if (
            player_character_active
            and consecutive_auto_turns >= self.auto_direct_max_auto_turns
        ):
            log.debug(
                "auto_direct_candidates: User controlled character has not spoken in a while."
            )
            return [scene.get_player_character()]

        # check if most recent character has spoken too many times in a row
        # if so then remove from candidates
        if repeat_count >= self.auto_direct_max_repeat_turns:
            log.debug(
                "auto_direct_candidates: Most recent character has spoken too many times in a row.",
                most_recent_character=most_recent_character,
            )
            candidates.pop(most_recent_character.name, None)

        # check if any characters have gone too long without speaking
        # if so collect into new list of candidates
        favored_candidates = []
        for name, turns in candidates.items():
            if turns > self.auto_direct_max_idle_turns:
                log.debug(
                    "auto_direct_candidates: Character has gone too long without speaking.",
                    character_name=name,
                    turns=turns,
                )
                favored_candidates.append(scene.get_character(name))

        if favored_candidates:
            return favored_candidates

        return [
            scene.get_character(character_name) for character_name in candidates.keys()
        ]

    # actions

    @set_processing
    async def auto_direct_set_scene_intent(
        self, require: bool = False
    ) -> ScenePhase | None:
        async def set_scene_intention(type: str, intention: str) -> ScenePhase:
            await set_scene_phase(self.scene, type, intention)
            self.scene.emit_status()
            return self.scene.intent_state.phase

        async def do_nothing(*args, **kwargs) -> None:
            return None

        focal_handler = focal.Focal(
            self.client,
            callbacks=[
                focal.Callback(
                    name="set_scene_intention",
                    arguments=[
                        focal.Argument(name="type", type="str"),
                        focal.Argument(name="intention", type="str"),
                    ],
                    fn=set_scene_intention,
                    multiple=False,
                ),
                focal.Callback(
                    name="do_nothing",
                    fn=do_nothing,
                    multiple=False,
                ),
            ],
            max_calls=1,
            scene=self.scene,
            scene_type_ids=", ".join(
                [
                    f'"{scene_type.id}"'
                    for scene_type in self.scene.intent_state.scene_types.values()
                ]
            ),
            retries=1,
            require=require,
        )

        await focal_handler.request(
            "director.direct-determine-scene-intent",
        )

        return self.scene.intent_state.phase

    @set_processing
    async def auto_direct_generate_scene_types(
        self,
        instructions: str,
        max_scene_types: int = 1,
    ):
        world_state_manager: WorldStateManager = self.scene.world_state_manager

        scene_type_templates: TypedCollection = await world_state_manager.get_templates(
            types=["scene_type"]
        )

        async def add_from_template(id: str) -> SceneType:
            template: TemplateSceneType | None = scene_type_templates.find_by_name(id)
            if not template:
                log.warning(
                    "auto_direct_generate_scene_types: Template not found.", name=id
                )
                return None
            return template.apply_to_scene(self.scene)

        async def generate_scene_type(
            id: str = None,
            name: str = None,
            description: str = None,
            instructions: str = None,
        ) -> SceneType:
            if not id or not name:
                return None

            scene_type = SceneType(
                id=id,
                name=name,
                description=description,
                instructions=instructions,
            )

            self.scene.intent_state.scene_types[id] = scene_type

            return scene_type

        focal_handler = focal.Focal(
            self.client,
            callbacks=[
                focal.Callback(
                    name="generate_scene_type",
                    arguments=[
                        focal.Argument(name="id", type="str"),
                        focal.Argument(name="name", type="str"),
                        focal.Argument(name="description", type="str"),
                        focal.Argument(name="instructions", type="str"),
                    ],
                    fn=generate_scene_type,
                    multiple=True,
                ),
                focal.Callback(
                    name="add_from_template",
                    arguments=[
                        focal.Argument(name="id", type="str"),
                    ],
                    fn=add_from_template,
                    multiple=True,
                ),
            ],
            max_calls=max_scene_types,
            retries=1,
            scene=self.scene,
            instructions=instructions,
            scene_type_templates=scene_type_templates.templates,
        )

        await focal_handler.request(
            "director.generate-scene-types",
        )
