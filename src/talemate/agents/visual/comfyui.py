import io
import random
import os
import base64
import time
import asyncio
import urllib.parse
from PIL import Image
import httpx
import structlog
import json
import pydantic

from talemate.agents.base import (
    AgentAction,
    AgentActionConditional,
    AgentActionConfig,
)

from .handlers import register
from .schema import Resolution, RenderSettings
from .style import STYLE_MAP, Style

log = structlog.get_logger("talemate.agents.visual.comfyui")

class Workflow(pydantic.BaseModel):
    nodes:dict 

    def set_resolution(self, resolution:Resolution):
        
        # will collect all latent image nodes
        # if there is multiple will look for the one with the 
        # title "Talemate Resolution"
        
        # if there is no latent image node with the title "Talemate Resolution"
        # the first latent image node will be used
        
        # resolution will be updated on the selected node
        
        # if no latent image node is found a warning will be logged
        
        latent_image_node = None
        
        for node_id, node in self.nodes.items():
            if node["class_type"] == "EmptyLatentImage":
                if not latent_image_node:
                    latent_image_node = node
                elif node["_meta"]["title"] == "Talemate Resolution":
                    latent_image_node = node
                    break
                
        if not latent_image_node:
            log.warning("set_resolution", error="No latent image node found")
            return 
        
        latent_image_node["inputs"]["width"] = resolution.width
        latent_image_node["inputs"]["height"] = resolution.height
        
        
    def set_prompt(self, prompt:str, negative_prompt:str = None):
        
        # will collect all CLIPTextEncode nodes
        
        # if there is multiple will look for the one with the
        # title "Talemate Positive Prompt" and "Talemate Negative Prompt"
        #
        # if there is no CLIPTextEncode node with the title "Talemate Positive Prompt"
        # the first CLIPTextEncode node will be used
        # 
        # if there is no CLIPTextEncode node with the title "Talemate Negative Prompt"
        # the second CLIPTextEncode node will be used
        # 
        # prompt will be updated on the selected node
        
        # if no CLIPTextEncode node is found an exception will be raised for 
        # the positive prompt
        
        # if no CLIPTextEncode node is found an exception will be raised for
        # the negative prompt if it is not None
        
        positive_prompt_node = None
        negative_prompt_node = None
        
        for node_id, node in self.nodes.items():
            
            if node["class_type"] == "CLIPTextEncode":
                if not positive_prompt_node:
                    positive_prompt_node = node
                elif node["_meta"]["title"] == "Talemate Positive Prompt":
                    positive_prompt_node = node
                elif not negative_prompt_node:
                    negative_prompt_node = node
                elif node["_meta"]["title"] == "Talemate Negative Prompt":
                    negative_prompt_node = node


        if not positive_prompt_node:
            raise ValueError("No positive prompt node found")
        
        positive_prompt_node["inputs"]["text"] = prompt
        
        if negative_prompt and not negative_prompt_node:
            raise ValueError("No negative prompt node found")                
    
        if negative_prompt:
            negative_prompt_node["inputs"]["text"] = negative_prompt        

    def set_checkpoint(self, checkpoint:str):
        
        # will collect all CheckpointLoaderSimple nodes
        # if there is multiple will look for the one with the
        # title "Talemate Load Checkpoint" 
        
        # if there is no CheckpointLoaderSimple node with the title "Talemate Load Checkpoint"
        # the first CheckpointLoaderSimple node will be used
        
        # checkpoint will be updated on the selected node
        
        # if no CheckpointLoaderSimple node is found a warning will be logged
        
        checkpoint_node = None
        
        for node_id, node in self.nodes.items():
            if node["class_type"] == "CheckpointLoaderSimple":
                if not checkpoint_node:
                    checkpoint_node = node
                elif node["_meta"]["title"] == "Talemate Load Checkpoint":
                    checkpoint_node = node
                    break
        
        if not checkpoint_node:
            log.warning("set_checkpoint", error="No checkpoint node found")
            return
        
        checkpoint_node["inputs"]["ckpt_name"] = checkpoint

    def set_seeds(self):
        for node in self.nodes.values():
            for field in node.get("inputs", {}).keys():
                if field == "noise_seed":
                    node["inputs"]["noise_seed"] = random.randint(0, 999999999999999)
                    
@register(backend_name="comfyui", label="ComfyUI")
class ComfyUIMixin:
    
    comfyui_default_render_settings = RenderSettings()
    
    EXTEND_ACTIONS = {
        "comfyui": AgentAction(
            enabled=True,
            condition=AgentActionConditional(
                attribute="_config.config.backend",
                value="comfyui"
            ),
            label="ComfyUI Settings",
            description="Setting overrides for the comfyui backend",
            config={
                "api_url": AgentActionConfig(
                    type="text",
                    value="http://localhost:8188",
                    label="API URL",
                    description="The URL of the backend API",
                ),
                "workflow": AgentActionConfig(
                    type="text",
                    value="default-sdxl.json",
                    label="Workflow",
                    description="The workflow to use for comfyui (workflow file name inside ./templates/comfyui-workflows)",
                ),
                "checkpoint": AgentActionConfig(
                    type="text",
                    value="default",
                    label="Checkpoint",
                    choices=[],
                    description="The main checkpoint to use.",
                ),
            }
        )
    }
    
    @property
    def comfyui_workflow_filename(self):
        base_name = self.actions["comfyui"].config["workflow"].value
        
        # make absolute path
        abs_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "templates", "comfyui-workflows", base_name)
        
        return abs_path
    
    @property
    def comfyui_workflow_is_sdxl(self) -> bool:
        """
        Returns true if `sdxl` is in worhflow file name (case insensitive)
        """
        
        return "sdxl" in self.comfyui_workflow_filename.lower()
    
    @property
    def comfyui_workflow(self) -> Workflow:
        workflow = self.comfyui_workflow_filename
        if not workflow:
            raise ValueError("No comfyui workflow file specified")
        
        with open(workflow, 'r') as f:
            return Workflow(nodes=json.load(f))
    
    @property
    async def comfyui_object_info(self):
        if hasattr(self, "_comfyui_object_info"):
            return self._comfyui_object_info
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url=f'{self.api_url}/object_info')
            self._comfyui_object_info = response.json()
            
        return self._comfyui_object_info
    
    @property
    async def comfyui_checkpoints(self):
        loader_node = (await self.comfyui_object_info)["CheckpointLoaderSimple"]
        _checkpoints = loader_node["input"]["required"]["ckpt_name"][0]
        return [
            {"label": checkpoint, "value": checkpoint} for checkpoint in _checkpoints    
        ]
        
    async def comfyui_get_image(self, filename:str, subfolder:str, folder_type:str):
        data = {"filename": filename, "subfolder": subfolder, "type": folder_type}
        url_values = urllib.parse.urlencode(data)
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url=f'{self.api_url}/view?{url_values}')
            return response.content
    
    async def comfyui_get_history(self, prompt_id:str):
        async with httpx.AsyncClient() as client:
            response = await client.get(url=f'{self.api_url}/history/{prompt_id}')
            return response.json()
        
    async def comfyui_get_images(self, prompt_id:str, max_wait:int=60.0):
        output_images = {}
        history = {}
        
        start = time.time()
        
        while not history:
            log.info("comfyui_get_images", waiting_for_history=True, prompt_id=prompt_id)
            history = await self.comfyui_get_history(prompt_id)
            await asyncio.sleep(1.0)
            if time.time() - start > max_wait:
                raise TimeoutError("Max wait time exceeded")
        
        for node_id, node_output in history[prompt_id]['outputs'].items():
            if 'images' in node_output:
                images_output = []
                for image in node_output['images']:
                    image_data = await self.comfyui_get_image(image['filename'], image['subfolder'], image['type'])
                    images_output.append(image_data)
            output_images[node_id] = images_output
                
        return output_images
            
    
    async def comfyui_generate(self, prompt:Style, format:str):
        url = self.api_url
        workflow = self.comfyui_workflow
        is_sdxl = self.comfyui_workflow_is_sdxl
        
        resolution = self.resolution_from_format(format, "sdxl" if is_sdxl else "sd15")
        
        workflow.set_resolution(resolution)
        workflow.set_prompt(prompt.positive_prompt, prompt.negative_prompt)
        workflow.set_seeds()
        workflow.set_checkpoint(self.actions["comfyui"].config["checkpoint"].value)
        
        payload = {"prompt": workflow.model_dump().get("nodes")}
        
        log.info("comfyui_generate", payload=payload, url=url)
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url=f'{url}/prompt', json=payload, timeout=90)
        
        log.info("comfyui_generate", response=response.text)
        
        r = response.json()
        
        prompt_id = r["prompt_id"]
        
        images = await self.comfyui_get_images(prompt_id)
        for node_id, node_images in images.items():
            for i, image in enumerate(node_images):
                await self.emit_image(base64.b64encode(image).decode("utf-8"))
                #image = Image.open(io.BytesIO(image))
                #image.save(f'comfyui-test.png')


    async def comfyui_apply_config(self, backend_changed:bool=False, *args, **kwargs):
        log.debug("comfyui_apply_config", backend_changed=backend_changed)
        if backend_changed and self.enabled:
            checkpoints = await self.comfyui_checkpoints
            selected_checkpoint = self.actions["comfyui"].config["checkpoint"].value
            self.actions["comfyui"].config["checkpoint"].choices = checkpoints
            self.actions["comfyui"].config["checkpoint"].value = selected_checkpoint
            
    async def comfyui_ready(self) -> bool:
        """
        Will send a GET to /system_stats and on 200 will return True
        """
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url=f'{self.api_url}/system_stats', timeout=2)
            return response.status_code == 200