import enum
import re
from dataclasses import dataclass, field

import isodate

_message_id = 0


def get_message_id():
    global _message_id
    _message_id += 1
    return _message_id


def reset_message_id():
    global _message_id
    _message_id = 0


class Flags(enum.IntFlag):
    """
    Flags for messages
    """

    NONE = 0
    HIDDEN = 1


@dataclass
class SceneMessage:
    """
    Base class for all messages that are sent to the scene.
    """

    # the mesage itself
    message: str

    # the id of the message
    id: int = field(default_factory=get_message_id)

    # the source of the message (e.g. "ai", "progress_story", "director")
    source: str = ""

    flags: Flags = Flags.NONE

    typ = "scene"

    def __str__(self):
        return self.message

    def __int__(self):
        return self.id

    def __len__(self):
        return len(self.message)

    def __in__(self, other):
        return other in self.message

    def __contains__(self, other):
        return self.message in other

    def __dict__(self):
        return {
            "message": self.message,
            "id": self.id,
            "typ": self.typ,
            "source": self.source,
            "flags": int(self.flags),
        }

    def __iter__(self):
        return iter(self.message)

    def split(self, *args, **kwargs):
        return self.message.split(*args, **kwargs)

    def startswith(self, *args, **kwargs):
        return self.message.startswith(*args, **kwargs)

    def endswith(self, *args, **kwargs):
        return self.message.endswith(*args, **kwargs)

    @property
    def secondary_source(self):
        return self.source

    @property
    def raw(self):
        return str(self.message)

    @property
    def hidden(self):
        return self.flags & Flags.HIDDEN

    def hide(self):
        self.flags |= Flags.HIDDEN

    def unhide(self):
        self.flags &= ~Flags.HIDDEN

    def as_format(self, format: str, **kwargs) -> str:
        if format == "movie_script":
            return self.message.rstrip("\n") + "\n"
        return self.message


@dataclass
class CharacterMessage(SceneMessage):
    typ = "character"
    source: str = "ai"

    def __str__(self):
        return self.message

    @property
    def character_name(self):
        return self.message.split(":", 1)[0]

    @property
    def secondary_source(self):
        return self.character_name

    @property
    def raw(self):
        return self.message.split(":", 1)[1].replace('"', "").replace("*", "").strip()

    @property
    def as_movie_script(self):
        """
        Returns the dialogue line as a script dialogue line.

        Example:
        {CHARACTER_NAME}
        {dialogue}
        """

        message = self.message.split(":", 1)[1].replace('"', "").strip()

        return f"\n{self.character_name.upper()}\n{message}\n"

    def as_format(self, format: str, **kwargs) -> str:
        if format == "movie_script":
            return self.as_movie_script
        return self.message


@dataclass
class NarratorMessage(SceneMessage):
    source: str = "progress_story"
    typ = "narrator"
    
@dataclass
class DirectorMessage(SceneMessage):
    action: str = "actor_instruction"
    typ = "director"

    @property
    def transformed_message(self):
        return self.message.replace("Director instructs ", "")

    @property
    def character_name(self):
        if self.action == "actor_instruction":
            return self.transformed_message.split(":", 1)[0]
        return ""

    @property
    def dialogue(self):
        if self.action == "actor_instruction":
            return self.transformed_message.split(":", 1)[1]
        return self.message

    @property
    def instructions(self):
        if self.action == "actor_instruction":
            return (
                self.dialogue.replace('"', "")
                .replace("To progress the scene, i want you to ", "")
                .strip()
            )
        return self.message

    @property
    def as_inner_monologue(self):

        # instructions may be written referencing the character as you, your etc.,
        # so we need to replace those to fit a first person perspective

        # first we lowercase
        instructions = self.instructions.lower()

        if not self.character_name:
            return instructions

        # then we replace yourself with myself using regex, taking care of word boundaries
        instructions = re.sub(r"\byourself\b", "myself", instructions)

        # then we replace your with my using regex, taking care of word boundaries
        instructions = re.sub(r"\byour\b", "my", instructions)

        # then we replace you with i using regex, taking care of word boundaries
        instructions = re.sub(r"\byou\b", "i", instructions)

        return f"{self.character_name} thinks: I should {instructions}"

    @property
    def as_story_progression(self):
        return f"{self.character_name}'s next action: {self.instructions}"

    def __dict__(self):
        rv = super().__dict__()

        if self.action:
            rv["action"] = self.action

        return rv

    def __str__(self):
        """
        The director message is a special case and needs to be transformed
        """
        return self.as_format("chat")

    def as_format(self, format: str, **kwargs) -> str:
        mode = kwargs.get("mode", "direction")
        if format == "movie_script":
            if mode == "internal_monologue":
                return f"\n({self.as_inner_monologue})\n"
            else:
                return f"\n({self.as_story_progression})\n"
        else:
            if mode == "internal_monologue":
                return f"# {self.as_inner_monologue}"
            else:
                return f"# {self.as_story_progression}"


@dataclass
class TimePassageMessage(SceneMessage):
    ts: str = "PT0S"
    source: str = "manual"
    typ = "time"

    def __dict__(self):
        return {
            "message": self.message,
            "id": self.id,
            "typ": "time",
            "source": self.source,
            "ts": self.ts,
            "flags": int(self.flags),
        }


@dataclass
class ReinforcementMessage(SceneMessage):
    typ = "reinforcement"

    @property
    def character_name(self):
        return self.source.split(":")[1]

    def __str__(self):
        question, _ = self.source.split(":", 1)
        return (
            f"# Internal notes for {self.character_name} - {question}: {self.message}"
        )

    def as_format(self, format: str, **kwargs) -> str:
        if format == "movie_script":
            message = str(self)[2:]
            return f"\n({message})\n"
        return self.message


MESSAGES = {
    "scene": SceneMessage,
    "character": CharacterMessage,
    "narrator": NarratorMessage,
    "director": DirectorMessage,
    "time": TimePassageMessage,
    "reinforcement": ReinforcementMessage,
}
