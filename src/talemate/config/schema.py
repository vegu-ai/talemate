import datetime
import os
from typing import TYPE_CHECKING, Any, ClassVar, Dict, Optional, TypeVar, Union, Literal

import pydantic
from pydantic import ConfigDict
import structlog
from typing_extensions import Annotated

import talemate.emit.async_signals as async_signals

from talemate.client.registry import get_client_class
from talemate.client.system_prompts import SystemPrompts

from talemate.path import SCENES_DIR

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

log = structlog.get_logger("talemate.config")

async_signals.register(
    "config.changed",
    "config.changed.follow",
)


class Client(pydantic.BaseModel):
    """
    LLM Client configuration
    """

    # clien type/provider (e.g., openai, anthropic, etc.)
    type: str
    name: str
    model: Union[str, None] = None
    api_url: Union[str, None] = None
    api_key: Union[str, None] = None
    # max input tokens to send with a generation request
    max_token_length: int = 8192

    # prefill text for ALL requests
    double_coercion: Union[str, None] = None

    # max requests per minute
    rate_limit: Union[int, None] = None

    # expected data structure format in responses
    data_format: Literal["json", "yaml"] | None = None

    enabled: bool = True

    # whether or not to enable reasoning
    reason_enabled: bool = False

    # add extra allowance for response tokens
    # this is useful for when the model generates visible thinking
    # tokens.
    reason_tokens: int = 0

    # regex to strip from the response if the model is reasoning
    reason_response_pattern: Union[str, None] = None

    # reason prefill - will be prepended to the prompt if the model is reasoning
    # this is mostly for base models that don't hhave reas
    reason_prefill: str | None = None

    # behavior when reasoning pattern is not found in the response
    # "fail" - raise an error (default, current behavior)
    # "ignore" - return response as is
    reason_failure_behavior: Literal["fail", "ignore"] = "fail"

    system_prompts: SystemPrompts = SystemPrompts()

    # inference preset group to use for this client
    preset_group: str | None = None

    # whether or not to lock the prompt template
    lock_template: bool = False

    @pydantic.field_validator("lock_template", mode="before")
    @classmethod
    def validate_lock_template(cls, v):
        if v is None:
            return False
        return v

    model_config = ConfigDict(extra="ignore")


ClientType = TypeVar("ClientType", bound=Client)


class AgentActionConfig(pydantic.BaseModel):
    value: Union[int, float, str, bool, list, None] = None


class AgentAction(pydantic.BaseModel):
    enabled: bool = True
    config: Union[dict[str, AgentActionConfig], None] = None


class Agent(pydantic.BaseModel):
    name: Union[str, None] = None
    client: Union[str, None] = None
    actions: Union[dict[str, AgentAction], None] = None
    enabled: bool = True

    model_config = ConfigDict(extra="ignore")

    # change serialization so actions and enabled are only
    # serialized if they are not None

    def model_dump(self, **kwargs):
        return super().model_dump(exclude_none=True)


class GamePlayerCharacter(pydantic.BaseModel):
    name: str = ""
    color: str = "#3362bb"
    gender: str = ""
    description: Optional[str] = ""

    model_config = ConfigDict(extra="ignore")


class General(pydantic.BaseModel):
    auto_save: bool = True
    auto_progress: bool = True
    max_backscroll: int = 100
    add_default_character: bool = True
    show_agent_activity_bar: bool = True


class StateReinforcementTemplate(pydantic.BaseModel):
    name: str
    query: str
    state_type: str = "npc"
    insert: str = "sequential"
    instructions: Union[str, None] = None
    description: Union[str, None] = None
    interval: int = 10
    auto_create: bool = False
    favorite: bool = False
    require_active: bool = True

    type: ClassVar = "state_reinforcement"


class WorldStateTemplates(pydantic.BaseModel):
    state_reinforcement: dict[str, StateReinforcementTemplate] = pydantic.Field(
        default_factory=dict
    )

    def get_template(self, name: str) -> Union[StateReinforcementTemplate, None]:
        return self.state_reinforcement.get(name)


class WorldState(pydantic.BaseModel):
    templates: WorldStateTemplates = WorldStateTemplates()


class Game(pydantic.BaseModel):
    default_player_character: GamePlayerCharacter = GamePlayerCharacter()
    general: General = General()
    world_state: WorldState = WorldState()

    model_config = ConfigDict(extra="ignore")


class CreatorConfig(pydantic.BaseModel):
    content_context: list[str] = [
        "a fun and engaging slice of life story aimed at an adult audience."
    ]


class OpenAIConfig(pydantic.BaseModel):
    api_key: Union[str, None] = None


class MistralAIConfig(pydantic.BaseModel):
    api_key: Union[str, None] = None


class AnthropicConfig(pydantic.BaseModel):
    api_key: Union[str, None] = None


class CohereConfig(pydantic.BaseModel):
    api_key: Union[str, None] = None


class GroqConfig(pydantic.BaseModel):
    api_key: Union[str, None] = None


class DeepSeekConfig(pydantic.BaseModel):
    api_key: Union[str, None] = None


class OpenRouterConfig(pydantic.BaseModel):
    api_key: Union[str, None] = None


class ElevenLabsConfig(pydantic.BaseModel):
    api_key: Union[str, None] = None
    model: str = "eleven_turbo_v2"


class CoquiConfig(pydantic.BaseModel):
    api_key: Union[str, None] = None


class GoogleConfig(pydantic.BaseModel):
    gcloud_credentials_path: Union[str, None] = None
    gcloud_location: Union[str, None] = None
    api_key: Union[str, None] = None


class RecentSceneCoverImage(pydantic.BaseModel):
    id: str
    file_type: str
    media_type: str


class RecentScene(pydantic.BaseModel):
    name: str
    path: str
    filename: str
    date: str
    cover_image: RecentSceneCoverImage | None = None


class EmbeddingFunctionPreset(pydantic.BaseModel):
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
    client: str | None = None


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
    }


class InferenceParameters(pydantic.BaseModel):
    temperature: float = 1.0
    temperature_last: bool = True
    top_p: float | None = 1.0
    top_k: int | None = 0
    min_p: float | None = 0.1
    presence_penalty: float | None = 0.2
    frequency_penalty: float | None = 0.05
    repetition_penalty: float | None = 1.0
    repetition_penalty_range: int | None = 1024

    xtc_threshold: float | None = 0.1
    xtc_probability: float | None = 0.0

    dry_multiplier: float | None = 0.0
    dry_base: float | None = 1.75
    dry_allowed_length: int | None = 2
    dry_sequence_breakers: str | None = '"\\n", ":", "\\"", "*"'
    adaptive_target: float | None = -0.01
    adaptive_decay: float | None = 0.9

    smoothing_factor: float | None = 0.0
    smoothing_curve: float | None = 1.0

    # this determines whether or not it should be persisted
    # to the config file
    changed: bool = False


class InferencePresets(pydantic.BaseModel):
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


class InferencePresetGroup(pydantic.BaseModel):
    name: str
    presets: InferencePresets


class Presets(pydantic.BaseModel):
    inference_defaults: InferencePresets = InferencePresets()
    inference: InferencePresets = InferencePresets()

    inference_groups: dict[str, InferencePresetGroup] = pydantic.Field(
        default_factory=dict
    )

    embeddings_defaults: dict[str, EmbeddingFunctionPreset] = pydantic.Field(
        default_factory=generate_chromadb_presets
    )
    embeddings: dict[str, EmbeddingFunctionPreset] = pydantic.Field(
        default_factory=generate_chromadb_presets
    )


def gnerate_intro_scenes():
    """
    When there are no recent scenes, generate from a set of introdutory scenes
    """

    scenes = [
        RecentScene(
            name="Simulation Suite V2",
            path=str(SCENES_DIR / "simulation-suite-v2" / "the-simulation-suite.json"),
            filename="the-simulation-suite.json",
            date=datetime.datetime.now().isoformat(),
            cover_image=RecentSceneCoverImage(
                id="7c6ae3e9cb58a9226513d5ce1e335b524c6c59e54793c94f707bdb8b25053c4f",
                file_type="png",
                media_type="image/png",
            ),
        ),
        RecentScene(
            name="Infinity Quest",
            path=str(SCENES_DIR / "infinity-quest" / "infinity-quest.json"),
            filename="infinity-quest.json",
            date=datetime.datetime.now().isoformat(),
            cover_image=RecentSceneCoverImage(
                id="8b22f95f2d03c4f453fba5c2129255649b77cf06c27998bdca8563287800eb3c",
                file_type="png",
                media_type="image/png",
            ),
        ),
        RecentScene(
            name="Infinity Quest Dynamic Story",
            path=str(
                SCENES_DIR / "infinity-quest-dynamic-story-v2" / "infinity-quest.json"
            ),
            filename="infinity-quest.json",
            date=datetime.datetime.now().isoformat(),
            cover_image=RecentSceneCoverImage(
                id="b3ad0c59ac4873e3b4323500ba00f70db6ec3d6ac45d9e97c0f64e38837a8c1a",
                file_type="png",
                media_type="image/png",
            ),
        ),
    ]

    return scenes


class RecentScenes(pydantic.BaseModel):
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
                    RecentSceneCoverImage(
                        **scene.assets.assets[scene.assets.cover_image].model_dump()
                    )
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


class HistoryMessageStyle(pydantic.BaseModel):
    italic: bool = False
    bold: bool = False

    # Leave None for default color
    color: str | None = None


class HidableHistoryMessageStyle(HistoryMessageStyle):
    # certain messages can be hidden, but all messages are shown by default
    show: bool = True


class MarkupMessageStyle(HistoryMessageStyle):
    # When False, use the underlying message default color instead of the markup color
    override_color: bool = True


class MessageAssetCadenceConfig(pydantic.BaseModel):
    cadence: Literal["always", "never", "on_change"] = "always"
    size: Literal["small", "medium", "big"] = "medium"


class SceneAppearance(pydantic.BaseModel):
    narrator_messages: HistoryMessageStyle = HistoryMessageStyle()
    actor_messages: HistoryMessageStyle = HistoryMessageStyle()
    director_messages: HidableHistoryMessageStyle = HidableHistoryMessageStyle()
    time_messages: HistoryMessageStyle = HistoryMessageStyle()
    context_investigation_messages: HidableHistoryMessageStyle = (
        HidableHistoryMessageStyle()
    )
    quotes: MarkupMessageStyle = MarkupMessageStyle()
    parentheses: MarkupMessageStyle = MarkupMessageStyle()
    brackets: MarkupMessageStyle = MarkupMessageStyle()
    emphasis: MarkupMessageStyle = MarkupMessageStyle()
    message_assets: Dict[str, MessageAssetCadenceConfig] = pydantic.Field(
        default_factory=lambda: {
            "avatar": MessageAssetCadenceConfig(),
            "card": MessageAssetCadenceConfig(),
            "scene_illustration": MessageAssetCadenceConfig(),
        }
    )

    auto_attach_assets: bool = True


class Appearance(pydantic.BaseModel):
    scene: SceneAppearance = SceneAppearance()


class Config(pydantic.BaseModel):
    clients: Dict[str, AnnotatedClient] = {}

    game: Game = Game()

    agents: Dict[str, Agent] = {}

    creator: CreatorConfig = CreatorConfig()

    openai: OpenAIConfig = OpenAIConfig()

    deepseek: DeepSeekConfig = DeepSeekConfig()

    mistralai: MistralAIConfig = MistralAIConfig()

    anthropic: AnthropicConfig = AnthropicConfig()

    openrouter: OpenRouterConfig = OpenRouterConfig()

    cohere: CohereConfig = CohereConfig()

    groq: GroqConfig = GroqConfig()

    google: GoogleConfig = GoogleConfig()

    elevenlabs: ElevenLabsConfig = ElevenLabsConfig()

    coqui: CoquiConfig = CoquiConfig()

    recent_scenes: RecentScenes = RecentScenes()

    presets: Presets = Presets()

    appearance: Appearance = Appearance()

    system_prompts: SystemPrompts = SystemPrompts()

    dirty: bool = pydantic.Field(default=False, exclude=True)

    model_config = ConfigDict(extra="ignore")

    async def set_dirty(self):
        self.dirty = True
        await async_signals.get("config.changed").send(self)
        await async_signals.get("config.changed.follow").send(self)


class SceneAssetUpload(pydantic.BaseModel):
    scene_cover_image: bool
    character_cover_image: str | None = None
    content: str = None
    vis_type: str | None = None
    character_name: str | None = None
