import enum
import re
import structlog
from typing import ClassVar, Literal

import pydantic

log = structlog.get_logger("talemate.scene_message")

__all__ = [
    "SceneMessage",
    "CharacterMessage",
    "NarratorMessage",
    "DirectorMessage",
    "TimePassageMessage",
    "ReinforcementMessage",
    "ContextInvestigationMessage",
    "MessageVersion",
    "VersionSource",
    "EMPTY_VERSIONS_PAYLOAD",
    "versions_payload_for",
    "Flags",
    "MESSAGES",
    "DIRECTOR_INPUT_PREFIX",
    "DIRECTOR_INPUT_PREFIX_YIELD",
]

VersionSource = Literal["original", "revision", "regenerate", "continue", "custom"]

# Default revision-stack shape for messages that don't (yet) have one —
# either no message_obj at all on a wire payload, or a message type that
# hasn't opted into versions. Keeps the wire schema homogeneous.
EMPTY_VERSIONS_PAYLOAD = {"versions": [], "active_version": 0}


def versions_payload_for(message_obj: "SceneMessage | None") -> dict:
    """Wire-emit revision-stack shape for ``message_obj``, falling back
    to :data:`EMPTY_VERSIONS_PAYLOAD` when no message is provided."""
    if message_obj is None:
        return EMPTY_VERSIONS_PAYLOAD
    return message_obj.versions_payload()


# Prefixes the user can type in the main input box to route a message to the
# director instead of having the player character speak/act. The yield variant
# must be checked first since it shares the single-character prefix.
DIRECTOR_INPUT_PREFIX = "#"
DIRECTOR_INPUT_PREFIX_YIELD = "##"

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

    NONE = 0x0
    HIDDEN = 0x1


class MessageVersion(pydantic.BaseModel):
    """One self-describing entry in a SceneMessage's version stack."""

    message: str
    source: VersionSource = "original"
    reason: str | None = None


class SceneMessage(pydantic.BaseModel):
    """
    Base class for all messages that are sent to the scene.
    """

    model_config = pydantic.ConfigDict(extra="ignore")

    # Subclasses opt in to revision-stack behavior by setting this to True.
    _supports_versions: ClassVar[bool] = False

    # the mesage itself
    message: str

    # the id of the message
    id: int = pydantic.Field(default_factory=get_message_id)

    # the source of the message (e.g. "ai", "progress_story", "director")
    source: str = ""

    meta: dict | None = None

    flags: Flags = Flags.NONE

    typ: str = "scene"

    rev: int = 0

    # Transient revision stack; seeded on opt-in subclasses, excluded
    # from to_dict / persistence.
    versions: list[MessageVersion] = pydantic.Field(
        default_factory=list, exclude=True, repr=False
    )

    active_version: int = pydantic.Field(default=0, exclude=True, repr=False)

    @pydantic.model_validator(mode="after")
    def _seed_initial_version(self):
        # Only opt-in subclasses get a stack. Skip seeding when an
        # explicit stack is supplied (model_validate / model_copy
        # overrides).
        if self._supports_versions and not self.versions:
            object.__setattr__(
                self,
                "versions",
                [MessageVersion(message=self.message, source="original")],
            )
            object.__setattr__(self, "active_version", 0)
        return self

    def __setattr__(self, name, value):
        # Keep `versions[active]` in lockstep with bare writes to
        # `.message` so streaming / in-flight cleanup don't drift the
        # canonical away from its stack entry.
        super().__setattr__(name, value)
        if (
            name == "message"
            and self._supports_versions
            and self.versions
            and 0 <= self.active_version < len(self.versions)
        ):
            self.versions[self.active_version].message = value

    def append_version(
        self,
        message: str,
        source: VersionSource,
        reason: str | None = None,
    ) -> MessageVersion:
        """
        Push a new version onto the stack, make it active, and update the
        canonical text. The only correct way to grow the stack.
        """
        if not self._supports_versions:
            raise TypeError(f"{type(self).__name__} does not support version history")
        version = MessageVersion(message=message, source=source, reason=reason)
        self.versions.append(version)
        # Use object.__setattr__ to bypass our own sync-back — we just
        # wrote versions[-1].message and don't want to overwrite it.
        object.__setattr__(self, "active_version", len(self.versions) - 1)
        object.__setattr__(self, "message", message)
        return version

    def set_active_version(self, index: int) -> None:
        """Move the active pointer; the canonical text follows."""
        if not self._supports_versions:
            raise TypeError(f"{type(self).__name__} does not support version history")
        if not (0 <= index < len(self.versions)):
            raise IndexError(
                f"active_version index {index} out of range [0, {len(self.versions)})"
            )
        object.__setattr__(self, "active_version", index)
        object.__setattr__(self, "message", self.versions[index].message)

    def versions_payload(self) -> dict:
        """
        Wire-emit shape for the revision stack. Returns
        :data:`EMPTY_VERSIONS_PAYLOAD` for message types that don't opt
        into versions so the wire payload stays homogeneous and the
        frontend doesn't need conditional handling.
        """
        if not self._supports_versions:
            return EMPTY_VERSIONS_PAYLOAD
        return {
            "versions": [v.model_dump() for v in self.versions],
            "active_version": self.active_version,
        }

    def __init__(self, message: str | None = None, **data):
        # Preserve the positional `message` construction style from the
        # dataclass era — many call sites pass it as the first positional arg.
        if message is not None:
            if "message" in data:
                raise TypeError(
                    f"{type(self).__name__}() got multiple values for 'message'"
                )
            data["message"] = message
        super().__init__(**data)

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

    def to_dict(self) -> dict:
        rv = {
            "message": self.message,
            "id": self.id,
            "typ": self.typ,
            "source": self.source,
            "flags": int(self.flags),
            "rev": self.rev,
        }

        if self.meta:
            rv["meta"] = self.meta

        return rv

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

    @property
    def fingerprint(self) -> str:
        """
        Returns a unique hash fingerprint for the message
        """
        return str(hash(self.message))[:16]

    @property
    def source_agent(self) -> str | None:
        return (self.meta or {}).get("agent", None)

    @property
    def source_function(self) -> str | None:
        return (self.meta or {}).get("function", None)

    @property
    def source_arguments(self) -> dict:
        return (self.meta or {}).get("arguments", {})

    @property
    def meta_hash(self) -> int:
        return hash(str(self.meta))

    def hide(self):
        self.flags |= Flags.HIDDEN

    def unhide(self):
        self.flags &= ~Flags.HIDDEN

    def as_format(self, format: str, **kwargs) -> str:
        if format in ("movie_script", "ai_aware"):
            return self.message.rstrip("\n") + "\n"
        elif format == "narrative":
            return self.message.strip()
        return self.message

    def set_source(self, agent: str, function: str, **kwargs):
        if not self.meta:
            self.meta = {}
        self.meta["agent"] = agent
        self.meta["function"] = function
        self.meta["arguments"] = kwargs

    def set_meta(self, **kwargs):
        if not self.meta:
            self.meta = {}
        self.meta.update(kwargs)


class CharacterMessage(SceneMessage):
    _supports_versions: ClassVar[bool] = True

    typ: str = "character"
    source: str = "ai"
    from_choice: str | None = None
    asset_id: str | None = None
    asset_type: Literal["avatar", "card", "scene_illustration"] | None = None

    def __str__(self):
        return self.message

    @staticmethod
    def with_name_prefix(name: str, body: str) -> str:
        """
        Return ``body`` formatted in the canonical ``"{name}: body"``
        shape, idempotently — adds the prefix only if it isn't already
        present.
        """
        prefix = f"{name}: "
        if body.startswith(prefix):
            return body
        return f"{prefix}{body}"

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
    def without_name(self) -> str:
        return self.message.split(":", 1)[1]

    @property
    def as_movie_script(self):
        """
        Returns the dialogue line as a script dialogue line.

        Example:
        {CHARACTER_NAME}
        {dialogue}
        """

        try:
            message = self.message.split(":", 1)[1].strip()
        except IndexError:
            log.warning(
                "character_message_as_movie_script failed to parse correct format",
                msg=self.message,
            )
            message = self.message

        return f"\n{self.character_name.upper()}\n{message}\nEND-OF-LINE\n"

    def to_dict(self) -> dict:
        rv = super().to_dict()

        if self.from_choice:
            rv["from_choice"] = self.from_choice

        # Include asset_id and asset_type if set
        if self.asset_id:
            rv["asset_id"] = self.asset_id
        if self.asset_type:
            rv["asset_type"] = self.asset_type

        return rv

    def as_format(self, format: str, **kwargs) -> str:
        if format in ("movie_script", "ai_aware"):
            return self.as_movie_script
        elif format == "narrative":
            return self.without_name.strip()
        return self.message


class NarratorMessage(SceneMessage):
    _supports_versions: ClassVar[bool] = True

    source: str = "ai"
    typ: str = "narrator"
    asset_id: str | None = None
    asset_type: Literal["avatar", "card", "scene_illustration"] | None = None

    def source_to_meta(self) -> dict:
        source = self.source
        action_name, *args = source.split(":")
        parameters = {}

        if action_name == "paraphrase":
            parameters["narration"] = args[0]
        elif action_name == "narrate_character_entry":
            parameters["character"] = args[0]
        elif action_name == "narrate_character_exit":
            parameters["character"] = args[0]
        elif action_name == "narrate_character":
            parameters["character"] = args[0]
        elif action_name == "narrate_query":
            parameters["query"] = args[0]
        elif action_name == "narrate_time_passage":
            parameters["duration"] = args[0]
            parameters["time_passed"] = args[1]
            parameters["narrative"] = args[2]
        elif action_name == "progress_story":
            parameters["narrative_direction"] = args[0]
        elif action_name == "narrate_after_dialogue":
            parameters["character"] = args[0]

        return {"agent": "narrator", "function": action_name, "arguments": parameters}

    def migrate_source_to_meta(self):
        if self.source and not self.meta:
            try:
                self.meta = self.source_to_meta()
            except Exception as e:
                log.debug(
                    "migrate_narrator_source_to_meta failed", error=e, msg=self.id
                )

        return self

    def to_dict(self) -> dict:
        rv = super().to_dict()

        if self.asset_id:
            rv["asset_id"] = self.asset_id
        if self.asset_type:
            rv["asset_type"] = self.asset_type

        return rv


class DirectorMessage(SceneMessage):
    action: str = "actor_instruction"
    source: str = "ai"
    typ: str = "director"
    subtype: Literal["function_call", "user_direction"] | None = None

    @property
    def character_name(self) -> str:
        return self.meta.get("character") if self.meta else None

    @property
    def instructions(self) -> str:
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

    @property
    def as_director_action(self) -> str:
        if not self.character_name:
            return f"{self.message}\n{self.action}"

    # Become aggressive towards Elmer as you no longer recognize the man.
    def migrate_message_to_meta(self):
        if self.message.startswith("Director instructs"):
            parts = self.message.split(":", 1)
            character_name = parts[0].replace("Director instructs ", "").strip()
            instructions = parts[1].strip()

            self.set_source(
                "director",
                "actor_instruction",
                character=character_name,
            )
            self.message = instructions
            self.source = "player"

        # Older saves dropped `subtype` from the serialized payload. Backfill it
        # from `action` so the frontend can still route to the correct variant.
        if self.subtype is None and self.action == "user_direction":
            self.subtype = "user_direction"

        return self

    def to_dict(self) -> dict:
        rv = super().to_dict()

        if self.action:
            rv["action"] = self.action
        if self.subtype:
            rv["subtype"] = self.subtype

        return rv

    def __str__(self):
        """
        The director message is a special case and needs to be transformed
        """
        return self.as_format("chat")

    def as_format(self, format: str, **kwargs) -> str:
        if not self.instructions.strip():
            return ""

        mode = kwargs.get("mode", "direction")
        if format in ["movie_script", "narrative", "ai_aware"]:
            if mode == "internal_monologue":
                return f"\n({self.as_inner_monologue})\n"
            else:
                return f"\n({self.as_story_progression})\n"
        else:
            if mode == "internal_monologue":
                return f"# {self.as_inner_monologue}"
            else:
                return f"# {self.as_story_progression}"


class TimePassageMessage(SceneMessage):
    ts: str = "PT0S"
    source: str = "manual"
    typ: str = "time"

    def to_dict(self) -> dict:
        rv = super().to_dict()
        rv["ts"] = self.ts
        return rv


class ReinforcementMessage(SceneMessage):
    typ: str = "reinforcement"
    source: str = "ai"

    @property
    def character_name(self):
        return self.source_arguments.get("character", "character")

    @property
    def question(self):
        return self.source_arguments.get("question", "question")

    def __str__(self):
        return f"# Internal note for {self.character_name} - {self.question}\n{self.message}"

    def as_format(self, format: str, **kwargs) -> str:
        if format in ["movie_script", "narrative", "ai_aware"]:
            message = str(self)[2:]
            return f"\n({message})\n"
        return f"\n{self.message}\n"

    def migrate_source_to_meta(self):
        if self.source and not self.meta:
            try:
                self.source_to_meta()
            except Exception as e:
                log.warning(
                    "migrate_reinforcement_source_to_meta", error=e, msg=self.id
                )

        return self

    def source_to_meta(self):
        source = self.source
        args = source.split(":")
        parameters = {"character": args[1], "question": args[0]}
        self.set_source("world_state", "update_reinforcement", **parameters)


class ContextInvestigationMessage(SceneMessage):
    _supports_versions: ClassVar[bool] = True

    typ: str = "context_investigation"
    source: str = "ai"
    sub_type: str | None = None
    asset_id: str | None = None
    asset_type: Literal["avatar", "card", "scene_illustration"] | None = None

    @property
    def character(self) -> str:
        return self.source_arguments.get("character", "character")

    @property
    def query(self) -> str:
        return self.source_arguments.get("query", "query")

    @property
    def title(self) -> str:
        """
        The title will differ based on sub_type

        Current sub_types:

        - visual-character
        - visual-scene
        - query
        - examine

        A natural language title will be generated based on the sub_type
        """

        if self.sub_type == "visual-character":
            return f"Visual description of {self.character} in the current moment"
        elif self.sub_type == "visual-scene":
            return "Visual description of the current moment"
        elif self.sub_type == "query":
            return f"Query: {self.query}"
        elif self.sub_type == "examine":
            entity = self.source_arguments.get("entity_name", "entity")
            return f"Added detail to {entity}"
        return "Internal note"

    def __str__(self):
        return f"# {self.title}: {self.message}"

    def to_dict(self) -> dict:
        rv = super().to_dict()
        rv["sub_type"] = self.sub_type

        if self.asset_id:
            rv["asset_id"] = self.asset_id
        if self.asset_type:
            rv["asset_type"] = self.asset_type

        return rv

    def as_format(self, format: str, **kwargs) -> str:
        if format in ["movie_script", "narrative", "ai_aware"]:
            message = str(self)[2:]
            return f"\n({message})\n".replace("*", "")
        return f"\n{self.message}\n".replace("*", "")


MESSAGES = {
    "scene": SceneMessage,
    "character": CharacterMessage,
    "narrator": NarratorMessage,
    "director": DirectorMessage,
    "time": TimePassageMessage,
    "reinforcement": ReinforcementMessage,
    "context_investigation": ContextInvestigationMessage,
}
