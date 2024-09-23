import copy
import datetime
import os
from typing import TYPE_CHECKING, Any, ClassVar, Dict, Optional, TypeVar, Union

import pydantic
import structlog
import yaml
from enum import Enum
from pydantic import BaseModel, Field
from typing_extensions import Annotated

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
    max_token_length: int = 8192
    double_coercion: Union[str, None] = None
    enabled: bool = True

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
    max_backscroll: int = 512


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


class MistralAIConfig(BaseModel):
    api_key: Union[str, None] = None


class AnthropicConfig(BaseModel):
    api_key: Union[str, None] = None


class CohereConfig(BaseModel):
    api_key: Union[str, None] = None


class GroqConfig(BaseModel):
    api_key: Union[str, None] = None


class RunPodConfig(BaseModel):
    api_key: Union[str, None] = None


class ElevenLabsConfig(BaseModel):
    api_key: Union[str, None] = None
    model: str = "eleven_turbo_v2"


class CoquiConfig(BaseModel):
    api_key: Union[str, None] = None


class GoogleConfig(BaseModel):
    gcloud_credentials_path: Union[str, None] = None
    gcloud_location: Union[str, None] = None


class TTSVoiceSamples(BaseModel):
    label: str
    value: str


class TTSConfig(BaseModel):
    device: str = "cuda"
    model: str = "tts_models/multilingual/multi-dataset/xtts_v2"
    voices: list[TTSVoiceSamples] = pydantic.Field(default_factory=list)


class RecentScene(BaseModel):
    name: str
    path: str
    filename: str
    date: str
    cover_image: Union[Asset, None] = None

class EmbeddingFunctionPreset(BaseModel):
    embeddings: str = "sentence-transformer"
    model: str = "all-MiniLM-L6-v2"
    trust_remote_code: bool = False
    device: str = "cpu"
    distance: float = 1.5
    distance_mod: int = 1
    distance_function: str = "l2"
    fast: bool = True
    gpu_recommendation: bool = False
    local: bool = True
    custom: bool = False



def generate_chromadb_presets() -> dict[str, EmbeddingFunctionPreset]:
    """
    Returns a dict of default embedding presets
    """
    
    return {
        "default": EmbeddingFunctionPreset(),
        "Alibaba-NLP/gte-base-en-v1.5": EmbeddingFunctionPreset(
            embeddings="sentence-transformer",
            model="Alibaba-NLP/gte-base-en-v1.5",
            trust_remote_code=True,
            distance=1,
            distance_function="cosine",
        ),
        "openai": EmbeddingFunctionPreset(
            embeddings="openai",
            model="text-embedding-3-small",
            distance=1,
            local=False,
        ),
        "hkunlp/instructor-xl": EmbeddingFunctionPreset(
            embeddings="instructor",
            model="hkunlp/instructor-xl",
            distance=1,
            local=True,
            fast=False,
            gpu_recommendation=True,
        ),
        "hkunlp/instructor-large": EmbeddingFunctionPreset(
            embeddings="instructor",
            model="hkunlp/instructor-large",
            distance=1,
            local=True,
            fast=False,
            gpu_recommendation=True,
        ),
        "hkunlp/instructor-base": EmbeddingFunctionPreset(
            embeddings="instructor",
            model="hkunlp/instructor-base",
            distance=1,
            local=True,
            fast=True,
        ),
    }


class InferenceParameters(BaseModel):
    temperature: float = 1.0
    temperature_last: bool = True
    top_p: float | None = 1.0
    top_k: int | None = 0
    min_p: float | None = 0.1
    presence_penalty: float | None = 0.2
    frequency_penalty: float | None = 0.05
    repetition_penalty: float | None = 1.0
    repetition_penalty_range: int | None = 1024
    # this determines whether or not it should be persisted
    # to the config file
    changed: bool = False


class InferencePresets(BaseModel):

    analytical: InferenceParameters = InferenceParameters(
        temperature=0.7,
        presence_penalty=0,
        frequency_penalty=0,
        repetition_penalty=1.0,
        min_p=0,
    )
    conversation: InferenceParameters = InferenceParameters(
        temperature=0.85, repetition_penalty_range=2048
    )
    creative: InferenceParameters = InferenceParameters()
    creative_instruction: InferenceParameters = InferenceParameters(
        temperature=0.85, repetition_penalty_range=512
    )
    deterministic: InferenceParameters = InferenceParameters(
        temperature=0.1,
        top_p=1,
        top_k=0,
        repetition_penalty=1.0,
        min_p=0,
    )
    scene_direction: InferenceParameters = InferenceParameters(
        temperature=0.85,
        min_p=0.0,
        presence_penalty=0.0,
    )
    summarization: InferenceParameters = InferenceParameters(
        temperature=0.7,
        min_p=0.0,
        presence_penalty=0.0,
    )


class Presets(BaseModel):
    inference_defaults: InferencePresets = InferencePresets()
    inference: InferencePresets = InferencePresets()
    
    embeddings_defaults: dict[str, EmbeddingFunctionPreset] = pydantic.Field(default_factory=generate_chromadb_presets)
    embeddings: dict[str, EmbeddingFunctionPreset] = pydantic.Field(default_factory=generate_chromadb_presets)


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


def validate_client_type(
    v: Any,
    handler: pydantic.ValidatorFunctionWrapHandler,
    info: pydantic.ValidationInfo,
):
    # clients can specify a custom config model in
    # client_cls.config_cls so we need to convert the
    # client config to the correct model

    # v is dict
    if isinstance(v, dict):
        client_cls = get_client_class(v.get("type"))
        if client_cls:
            config_cls = getattr(client_cls, "config_cls", None)
            if config_cls:
                return config_cls(**v)
            else:
                return handler(v)
    # v is Client instance
    elif isinstance(v, Client):
        client_cls = get_client_class(v.type)
        if client_cls:
            config_cls = getattr(client_cls, "config_cls", None)
            if config_cls:
                return config_cls(**v.model_dump())
            else:
                return handler(v)


AnnotatedClient = Annotated[
    ClientType,
    pydantic.WrapValidator(validate_client_type),
]


class Config(BaseModel):
    clients: Dict[str, AnnotatedClient] = {}

    game: Game = Game()

    agents: Dict[str, Agent] = {}

    creator: CreatorConfig = CreatorConfig()

    openai: OpenAIConfig = OpenAIConfig()

    mistralai: MistralAIConfig = MistralAIConfig()

    anthropic: AnthropicConfig = AnthropicConfig()

    cohere: CohereConfig = CohereConfig()

    groq: GroqConfig = GroqConfig()

    runpod: RunPodConfig = RunPodConfig()

    google: GoogleConfig = GoogleConfig()

    elevenlabs: ElevenLabsConfig = ElevenLabsConfig()

    coqui: CoquiConfig = CoquiConfig()

    tts: TTSConfig = TTSConfig()

    recent_scenes: RecentScenes = RecentScenes()

    presets: Presets = Presets()

    class Config:
        extra = "ignore"

    def save(self, file_path: str = "./config.yaml"):
        save_config(self, file_path)


class SceneConfig(BaseModel):
    automated_actions: dict[str, bool]


class SceneAssetUpload(BaseModel):
    scene_cover_image: bool
    character_cover_image: str | None = None
    content: str = None


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
            config = Config(**config).model_dump(exclude_none=True)
        except pydantic.ValidationError as e:
            log.error("config validation", error=e)
            return None

    # we dont want to persist the following, so we drop them:
    # - presets.inference_defaults
    # - presets.embeddings_defaults
    
    if "inference_defaults" in config["presets"]:
        config["presets"].pop("inference_defaults")
        
    if "embeddings_defaults" in config["presets"]:
        config["presets"].pop("embeddings_defaults")
    
    # for normal presets we only want to persist if they have changed
    for preset_name, preset in list(config["presets"]["inference"].items()):
        if not preset.get("changed"):
            config["presets"]["inference"].pop(preset_name)

    # if presets is empty, remove it
    if not config["presets"]["inference"]:
        config.pop("presets")

    with open(file_path, "w") as file:
        yaml.dump(config, file)

    emit("config_saved", data=config)


def cleanup() -> Config:

    log.info("cleaning up config")

    config = load_config(as_model=True)

    cleanup_removed_clients(config)
    cleanup_removed_agents(config)

    save_config(config)

    return config


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
