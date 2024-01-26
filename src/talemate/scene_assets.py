from __future__ import annotations
from typing import TYPE_CHECKING, Any
import os
import pydantic
import hashlib
import base64

if TYPE_CHECKING:
    from talemate import Scene
    
import structlog

__all__ = [
    "Asset",
    "SceneAssets"
]

log = structlog.get_logger("talemate.scene_assets")

class Asset(pydantic.BaseModel):
    id: str
    file_type: str
    media_type: str
    
    def to_base64(self, asset_directory:str) -> str:
        
        """
        Returns the asset as a base64 encoded string.
        """
        
        asset_path = os.path.join(asset_directory, f"{self.id}.{self.file_type}")
        
        with open(asset_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    
class SceneAssets:

    def __init__(self, scene:Scene):
        self.scene = scene
        self.assets = {}
        self.cover_image = None

    @property
    def asset_directory(self):
        """
        Returns the scene's asset path
        """
        
        scene_save_dir = self.scene.save_dir
        
        if not os.path.exists(scene_save_dir):
            raise FileNotFoundError(f"Scene save directory does not exist: {scene_save_dir}")
        
        asset_path = os.path.join(scene_save_dir, "assets")
        
        if not os.path.exists(asset_path):
            os.makedirs(asset_path)
            
        return asset_path
    
    def asset_path(self, asset_id:str) -> str:
        
        """
        Returns the path to the asset with the given id.
        """
        try:
            return os.path.join(self.asset_directory, f"{asset_id}.{self.assets[asset_id].file_type}")
        except KeyError:
            log.error("asset_path", asset_id=asset_id, assets=self.assets)
            return None
        
    def dict(self, *args, **kwargs):
        return {
            "cover_image": self.cover_image,
            "assets": {
                asset.id: asset.dict() for asset in self.assets.values()
            }
        }
    
    
    def load_assets(self, assets_dict:dict):
            
            """
            Loads assets from a dictionary.
            """
            
            for asset_id, asset_dict in assets_dict.items():
                self.assets[asset_id] = Asset(**asset_dict)
    
    def set_cover_image(self, asset_bytes:bytes, file_extension:str, media_type:str):
        # add the asset
        
        asset = self.add_asset(asset_bytes, file_extension, media_type)
        self.cover_image = asset.id

    def set_cover_image_from_file_path(self, file_path:str):
            
        """
        Sets the cover image from file path, calling add_asset_from_file_path
        """
        
        asset = self.add_asset_from_file_path(file_path)
        self.cover_image = asset.id        
    
    def add_asset(self, asset_bytes:bytes, file_extension:str, media_type:str) -> Asset:
        """
        Takes the asset and stores it in the scene's assets folder.
        """

        # generate a hash for the asset using the content of the image
        # this will be used as the filename
        asset_id = hashlib.sha256(asset_bytes).hexdigest()

        # if the asset already exists, return the existing asset
        if asset_id in self.assets:
            return self.assets[asset_id]

        # create the asset path if it doesn't exist
        asset_path = self.asset_directory

        # create the asset file path
        asset_file_path = os.path.join(asset_path, f"{asset_id}.{file_extension}")

        # store the asset
        with open(asset_file_path, "wb") as f:
            f.write(asset_bytes)

        # create the asset object
        asset = Asset(id=asset_id, file_type=file_extension, media_type=media_type)

        self.assets[asset_id] = asset

        return asset
    

    def add_asset_from_image_data(self, image_data:str) -> Asset:
        """
        Will add an asset from an image data, extracting media type from the
        data url and then decoding the base64 encoded data.
        
        Will call add_asset
        """
        
        media_type = image_data.split(";")[0].split(":")[1]
        image_bytes = base64.b64decode(image_data.split(",")[1])
        file_extension = media_type.split("/")[1]
        
        return self.add_asset(image_bytes, file_extension, media_type)
        
    
    def add_asset_from_file_path(self, file_path:str) -> Asset:
        
        """
        Will add an asset from a file path, first loading the file into memory.
        and then calling add_asset
        """
        
        file_bytes = None
        with open(file_path, "rb") as f:
            file_bytes = f.read()
            
        file_extension = os.path.splitext(file_path)[1]
        
        # guess media type from extension, currently only supports images
        # for png, jpg and webp
        
        if file_extension == ".png":
            media_type = "image/png"
        elif file_extension in [".jpg", ".jpeg"]:
            media_type = "image/jpeg"
        elif file_extension == ".webp":
            media_type = "image/webp"
        else:
            raise ValueError(f"Unsupported file extension: {file_extension}")
        
        return self.add_asset(file_bytes, file_extension, media_type)    
    
    def get_asset(self, asset_id:str) -> Asset:
        
        """
        Returns the asset with the given id.
        """
        
        return self.assets[asset_id]
    
    def get_asset_bytes(self, asset_id:str) -> bytes:
            
        """
        Returns the bytes of the asset with the given id.
        """
        
        asset_path = self.asset_path(asset_id)
        
        with open(asset_path, "rb") as f:
            return f.read()
    
    
    def get_asset_bytes_as_base64(self, asset_id:str) -> str:
        
        """
        Returns the bytes of the asset with the given id as a base64 encoded string.
        """
        
        bytes = self.get_asset_bytes(asset_id)
        
        return base64.b64encode(bytes).decode("utf-8")
    
    def remove_asset(self, asset_id:str):
        
        """
        Removes the asset with the given id.
        """
        
        asset = self.assets.pop(asset_id)
        
        asset_path = self.asset_directory
        
        asset_file_path = os.path.join(asset_path, f"{asset_id}.{asset.file_type}")
        
        os.remove(asset_file_path)    
    
