import datetime
import os
from typing import TYPE_CHECKING, ClassVar, Dict, Optional, TypeVar, Union

import pydantic
import structlog
import yaml
from pydantic import BaseModel, Field

from talemate.agents.registry import get_agent_class
from talemate.client.registry import get_client_class
from talemate.emit import emit
from talemate.scene_assets import Asset

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

log = structlog.get_logger("talemate.config")


def scenes_dir():
    relative_path = os.path.join(
        os.path.dirname(os.path.realpath(__file__)),
        "..",
        "..",
        "scenes",
    )
    return os.path.abspath(relative_path)


class Client(BaseModel):
    type: str
    name: str
    model: Union[str, None] = None
    api_url: Union[str, None] = None
    api_key: Union[str, None] = None
    max_token_length: int = 4096

    class Config:
        extra = "ignore"


ClientType = TypeVar("ClientType", bound=Client)


class AgentActionConfig(BaseModel):
    value: Union[int, float, str, bool, None] = None


class AgentAction(BaseModel):
    enabled: bool = True
    config: Union[dict[str, AgentActionConfig], None] = None


class Agent(BaseModel):
    name: Union[str, None] = None
    client: Union[str, None] = None
    actions: Union[dict[str, AgentAction], None] = None
    enabled: bool = True

    class Config:
        extra = "ignore"

    # change serialization so actions and enabled are only
    # serialized if they are not None

    def model_dump(self, **kwargs):
        return super().model_dump(exclude_none=True)


class GamePlayerCharacter(BaseModel):
    name: str = ""
    color: str = "#3362bb"
    gender: str = ""
    description: Optional[str] = ""

    class Config:
        extra = "ignore"


class General(BaseModel):
    auto_save: bool = True
    auto_progress: bool = True


class StateReinforcementTemplate(BaseModel):
    name: str
    query: str
    state_type: str = "npc"
    insert: str = "sequential"
    instructions: Union[str, None] = None
    description: Union[str, None] = None
    interval: int = 10
    auto_create: bool = False
    favorite: bool = False

    type: ClassVar = "state_reinforcement"


class WorldStateTemplates(BaseModel):
    state_reinforcement: dict[str, StateReinforcementTemplate] = pydantic.Field(
        default_factory=dict
    )

    def get_template(self, name: str) -> Union[StateReinforcementTemplate, None]:
        return self.state_reinforcement.get(name)


class WorldState(BaseModel):
    templates: WorldStateTemplates = WorldStateTemplates()


class Game(BaseModel):
    default_player_character: GamePlayerCharacter = GamePlayerCharacter()
    general: General = General()
    world_state: WorldState = WorldState()

    class Config:
        extra = "ignore"


class CreatorConfig(BaseModel):
    content_context: list[str] = [
        "a fun and engaging slice of life story aimed at an adult audience."
    ]


class OpenAIConfig(BaseModel):
    api_key: Union[str, None] = None


class RunPodConfig(BaseModel):
    api_key: Union[str, None] = None


class ElevenLabsConfig(BaseModel):
    api_key: Union[str, None] = None
    model: str = "eleven_turbo_v2"


class CoquiConfig(BaseModel):
    api_key: Union[str, None] = None


class TTSVoiceSamples(BaseModel):
    label: str
    value: str


class TTSConfig(BaseModel):
    device: str = "cuda"
    model: str = "tts_models/multilingual/multi-dataset/xtts_v2"
    voices: list[TTSVoiceSamples] = pydantic.Field(default_factory=list)


class ChromaDB(BaseModel):
    instructor_device: str = "cpu"
    instructor_model: str = "default"
    openai_model: str = "text-embedding-3-small"
    embeddings: str = "default"


class RecentScene(BaseModel):
    name: str
    path: str
    filename: str
    date: str
    cover_image: Union[Asset, None] = None


def gnerate_intro_scenes():
    """
    When there are no recent scenes, generate from a set of introdutory scenes
    """

    scenes = [
        RecentScene(
            name="Simulation Suite",
            path=os.path.join(
                scenes_dir(), "simulation-suite", "simulation-suite.json"
            ),
            filename="simulation-suite.json",
            date=datetime.datetime.now().isoformat(),
            cover_image=Asset(
                id="4b157dccac2ba71adb078a9d591f9900d6d62f3e86168a5e0e5e1e9faf6dc103",
                file_type="png",
                media_type="image/png",
            ),
        ),
        RecentScene(
            name="Infinity Quest",
            path=os.path.join(scenes_dir(), "infinity-quest", "infinity-quest.json"),
            filename="infinity-quest.json",
            date=datetime.datetime.now().isoformat(),
            cover_image=Asset(
                id="52b1388ed6f77a43981bd27e05df54f16e12ba8de1c48f4b9bbcb138fa7367df",
                file_type="png",
                media_type="image/png",
            ),
        ),
        RecentScene(
            name="Infinity Quest Dynamic Scenario",
            path=os.path.join(
                scenes_dir(), "infinity-quest-dynamic-scenario", "infinity-quest.json"
            ),
            filename="infinity-quest.json",
            date=datetime.datetime.now().isoformat(),
            cover_image=Asset(
                id="e7c712a0b276342d5767ba23806b03912d10c7c4b82dd1eec0056611e2cd5404",
                file_type="png",
                media_type="image/png",
            ),
        ),
    ]

    return scenes


class RecentScenes(BaseModel):
    scenes: list[RecentScene] = pydantic.Field(default_factory=gnerate_intro_scenes)
    max_entries: int = 10

    def push(self, scene: "Scene"):
        """
        adds a scene to the recent scenes list
        """

        # if scene has not been saved, don't add it
        if not scene.full_path:
            return

        now = datetime.datetime.now()

        # remove any existing entries for this scene
        self.scenes = [s for s in self.scenes if s.path != scene.full_path]

        # add the new entry
        self.scenes.insert(
            0,
            RecentScene(
                name=scene.name,
                path=scene.full_path,
                filename=scene.filename,
                date=now.isoformat(),
                cover_image=(
                    scene.assets.assets[scene.assets.cover_image]
                    if scene.assets.cover_image
                    else None
                ),
            ),
        )

        # trim the list to max_entries
        self.scenes = self.scenes[: self.max_entries]

    def clean(self):
        """
        removes any entries that no longer exist
        """

        self.scenes = [s for s in self.scenes if os.path.exists(s.path)]


class Config(BaseModel):
    clients: Dict[str, ClientType] = {}

    game: Game

    agents: Dict[str, Agent] = {}

    creator: CreatorConfig = CreatorConfig()

    openai: OpenAIConfig = OpenAIConfig()

    runpod: RunPodConfig = RunPodConfig()

    chromadb: ChromaDB = ChromaDB()

    elevenlabs: ElevenLabsConfig = ElevenLabsConfig()

    coqui: CoquiConfig = CoquiConfig()

    tts: TTSConfig = TTSConfig()

    recent_scenes: RecentScenes = RecentScenes()

    class Config:
        extra = "ignore"

    def save(self, file_path: str = "./config.yaml"):
        save_config(self, file_path)


class SceneConfig(BaseModel):
    automated_actions: dict[str, bool]


class SceneAssetUpload(BaseModel):
    scene_cover_image: bool
    character_cover_image: str = None
    content: str = None


def prepare_client_config(clients: dict) -> dict:
    # client's can specify a custom config model in
    # client_cls.config_cls so we need to convert the
    # client config to the correct model

    for client_name, client_config in clients.items():
        client_cls = get_client_class(client_config.get("type"))
        if client_cls:
            config_cls = getattr(client_cls, "config_cls", None)
            if config_cls:
                clients[client_name] = config_cls(**client_config)


def load_config(
    file_path: str = "./config.yaml", as_model: bool = False
) -> Union[dict, Config]:
    """
    Load the config file from the given path.

    Should cache the config and only reload if the file modification time
    has changed since the last load
    """

    with open(file_path, "r") as file:
        config_data = yaml.safe_load(file)

    try:
        prepare_client_config(config_data.get("clients", {}))
        config = Config(**config_data)
        config.recent_scenes.clean()
    except pydantic.ValidationError as e:
        log.error("config validation", error=e)
        return None

    if as_model:
        return config

    return config.model_dump()


def save_config(config, file_path: str = "./config.yaml"):
    """
    Save the config file to the given path.
    """

    log.debug("Saving config", file_path=file_path)

    # If config is a Config instance, convert it to a dictionary
    if isinstance(config, Config):
        config = config.model_dump(exclude_none=True)
    elif isinstance(config, dict):
        # validate
        try:
            prepare_client_config(config.get("clients", {}))
            config = Config(**config).model_dump(exclude_none=True)
        except pydantic.ValidationError as e:
            log.error("config validation", error=e)
            return None

    with open(file_path, "w") as file:
        yaml.dump(config, file)

    emit("config_saved", data=config)


def cleanup():

    log.info("cleaning up config")

    config = load_config(as_model=True)

    cleanup_removed_clients(config)
    cleanup_removed_agents(config)

    save_config(config)


def cleanup_removed_clients(config: Config):
    """
    Will remove any clients that are no longer present
    """

    if not config:
        return

    for client_in_config in list(config.clients.keys()):
        client_config = config.clients[client_in_config]
        if not get_client_class(client_config.type):
            log.info("removing client from config", client=client_in_config)
            del config.clients[client_in_config]


def cleanup_removed_agents(config: Config):
    """
    Will remove any agents that are no longer present
    """

    if not config:
        return

    for agent_in_config in list(config.agents.keys()):
        if not get_agent_class(agent_in_config):
            log.info("removing agent from config", agent=agent_in_config)
            del config.agents[agent_in_config]
