import yaml
import pydantic
import structlog
import os

from pydantic import BaseModel
from typing import Optional, Dict, Union

from talemate.emit import emit

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

class Game(BaseModel):
    default_player_character: GamePlayerCharacter = GamePlayerCharacter()
    general: General = General()
    
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
    
    class Config:
        extra = "ignore"

class SceneConfig(BaseModel):
    automated_actions: dict[str, bool]
    
class SceneAssetUpload(BaseModel):
    scene_cover_image:bool
    character_cover_image:str = None
    content:str = None
    

def load_config(file_path: str = "./config.yaml") -> dict:
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