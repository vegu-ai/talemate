import yaml
import pydantic
import structlog
import os

from pydantic import BaseModel
from typing import Optional, Dict, Union

log = structlog.get_logger("talemate.config")

class Client(BaseModel):
    type: str
    name: str
    model: Optional[str]
    api_url: Optional[str]
    max_token_length: Optional[int]
    
    class Config:
        extra = "ignore"

class Agent(BaseModel):
    name: str
    client: str = None
    
    class Config:
        extra = "ignore"

class GamePlayerCharacter(BaseModel):
    name: str
    color: str
    gender: str
    description: Optional[str]

    class Config:
        extra = "ignore"


class Game(BaseModel):
    default_player_character: GamePlayerCharacter
    
    class Config:
        extra = "ignore"

class CreatorConfig(BaseModel):
    content_context: list[str] = ["a fun and engaging slice of life story aimed at an adult audience."]

class OpenAIConfig(BaseModel):
    api_key: Union[str,None]=None
    
class RunPodConfig(BaseModel):
    api_key: Union[str,None]=None

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

    return config.dict()


def save_config(config, file_path: str = "./config.yaml"):
    """
    Save the config file to the given path.
    """
    
    log.debug("Saving config", file_path=file_path)
    
    # If config is a Config instance, convert it to a dictionary
    if isinstance(config, Config):
        config = config.dict()
    elif isinstance(config, dict):
        # validate
        try:
            config = Config(**config).dict()
        except pydantic.ValidationError as e:
            log.error("config validation", error=e)
            return None

    with open(file_path, "w") as file:
        yaml.dump(config, file)