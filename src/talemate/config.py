import yaml
import pydantic
import structlog
import os
import datetime

from pydantic import BaseModel, Field
from typing import Optional, Dict, Union, ClassVar, TYPE_CHECKING

from talemate.emit import emit
from talemate.scene_assets import Asset

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

log = structlog.get_logger("talemate.config")

class Client(BaseModel):
    type: str
    name: str
    model: Union[str,None] = None
    api_url: Union[str,None] = None
    max_token_length: Union[int,None] = None
    
    class Config:
        extra = "ignore"
 

class AgentActionConfig(BaseModel):
    value: Union[int, float, str, bool, None] = None
        
class AgentAction(BaseModel):
    enabled: bool = True
    config: Union[dict[str, AgentActionConfig], None] = None

class Agent(BaseModel):
    name: Union[str,None] = None
    client: Union[str,None] = None
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
    
    type:ClassVar = "state_reinforcement"
    
class WorldStateTemplates(BaseModel):
    state_reinforcement: dict[str, StateReinforcementTemplate] = pydantic.Field(default_factory=dict)
    
class WorldState(BaseModel):
    templates: WorldStateTemplates =  WorldStateTemplates()
    
class Game(BaseModel):
    default_player_character: GamePlayerCharacter = GamePlayerCharacter()
    general: General = General()
    world_state: WorldState = WorldState()
    
    class Config:
        extra = "ignore"

class CreatorConfig(BaseModel):
    content_context: list[str] = ["a fun and engaging slice of life story aimed at an adult audience."]

class OpenAIConfig(BaseModel):
    api_key: Union[str,None]=None
    
class RunPodConfig(BaseModel):
    api_key: Union[str,None]=None
    
class ElevenLabsConfig(BaseModel):
    api_key: Union[str,None]=None
    model: str = "eleven_turbo_v2"
    
class CoquiConfig(BaseModel):
    api_key: Union[str,None]=None
    
class TTSVoiceSamples(BaseModel):
    label:str
    value:str

class TTSConfig(BaseModel):
    device:str = "cuda"
    model:str = "tts_models/multilingual/multi-dataset/xtts_v2"
    voices: list[TTSVoiceSamples] = pydantic.Field(default_factory=list)

class ChromaDB(BaseModel):
    instructor_device: str="cpu"
    instructor_model: str="default"
    embeddings: str="default"

class RecentScene(BaseModel):
    name: str
    path: str
    filename: str
    date: str
    cover_image: Asset = None
    
class RecentScenes(BaseModel):
    scenes: list[RecentScene] = pydantic.Field(default_factory=list)
    max_entries: int = 10

    def push(self, scene:"Scene"):
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
        self.scenes.insert(0, 
            RecentScene(
                name=scene.name, 
                path=scene.full_path, 
                filename=scene.filename,
                date=now.isoformat(), 
                cover_image=scene.assets.assets[scene.assets.cover_image] if scene.assets.cover_image else None
            ))
        
        # trim the list to max_entries
        self.scenes = self.scenes[:self.max_entries]


class Config(BaseModel):
    clients: Dict[str, Client] = {}
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
    scene_cover_image:bool
    character_cover_image:str = None
    content:str = None
    

def load_config(file_path: str = "./config.yaml", as_model:bool=False) -> Union[dict, Config]:
    """
    Load the config file from the given path.
    
    Should cache the config and only reload if the file modification time
    has changed since the last load
    """
    
    with open(file_path, "r") as file:
        config_data = yaml.safe_load(file)

    try:
        config = Config(**config_data)
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

    with open(file_path, "w") as file:
        yaml.dump(config, file)
        
    emit("config_saved", data=config)