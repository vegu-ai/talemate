import asyncio
import pydantic
import structlog
import httpx
import json
import time
import urllib.parse
import random
import hashlib
from pathlib import Path

# import talemate.agents.visual.automatic1111  # noqa: F401
# import talemate.agents.visual.comfyui  # noqa: F401
# import talemate.agents.visual.openai_image  # noqa: F401
from talemate.agents.base import (
    AgentAction,
    AgentActionConfig,
    AgentActionConditional,
)
from talemate.instance import get_agent
from talemate.path import TEMPLATES_DIR
import talemate.agents.visual.backends as backends
from talemate.agents.visual.backends.utils import (
    normalize_api_url,
    get_resolution_choices,
)
from talemate.agents.visual.schema import (
    GenerationRequest,
    GenerationResponse,
    Resolution,
    GEN_TYPE,
    PROMPT_TYPE,
)

log = structlog.get_logger("talemate.agents.visual.comfyui")

WORKFLOW_DIR = TEMPLATES_DIR / "comfyui-workflows"

WORKFLOW_CACHE: dict[str, "Workflow"] = {}

BACKEND_NAME = "comfyui"

MODEL_RETRIEVAL_MAP = [
    ("CheckpointLoaderSimple", "ckpt_name", "checkpoint"),
    ("UnetLoaderGGUF", "unet_name", "unet"),
    ("UNETLoader", "unet_name", "unet"),
]

MODEL_TYPES = list(set([model_type for _, _, model_type in MODEL_RETRIEVAL_MAP]))


class Model(pydantic.BaseModel):
    name: str
    label: str
    value: str


class Models(pydantic.BaseModel):
    checkpoint: list[Model] = pydantic.Field(default=[])
    unet: list[Model] = pydantic.Field(default=[])

    @classmethod
    def from_info(cls, info: dict) -> "Models":
        models = {}
        for node_type, input_key, model_type in MODEL_RETRIEVAL_MAP:
            try:
                if model_type not in models:
                    models[model_type] = []
                _models = [
                    Model(name=model, label=model, value=model)
                    for model in info[node_type]["input"]["required"][input_key][0]
                ]
                models[model_type].extend(_models)
            except KeyError:
                log.debug(f"No {node_type} found in object info", info=info)
        return cls(**models)

    def get_choices(self, model_type: str | None, add_empty: bool = True) -> list[dict]:
        if not model_type:
            return [{"label": "- Workflow default -", "value": ""}]
        models = getattr(self, model_type)
        choices = [model.model_dump() for model in models]
        if add_empty:
            choices.insert(0, {"label": "- Workflow default -", "value": ""})
        return choices


class Workflow(pydantic.BaseModel):
    nodes: dict
    mtime: float
    path: str

    _max_references: int | None = pydantic.PrivateAttr(default=None)

    @property
    def resolution_node(self) -> dict | None:
        for node_id, node in self.nodes.items():
            if node["_meta"]["title"] == "Talemate Resolution":
                return node
        return None

    @property
    def positive_prompt_node(self) -> dict | None:
        for node_id, node in self.nodes.items():
            if node["_meta"]["title"] == "Talemate Positive Prompt":
                return node
        return None

    @property
    def negative_prompt_node(self) -> dict | None:
        for node_id, node in self.nodes.items():
            if node["_meta"]["title"] == "Talemate Negative Prompt":
                return node
        return None

    @property
    def main_model_node(self) -> dict | None:
        for node_id, node in self.nodes.items():
            if (
                node["_meta"]["title"] == "Talemate Load Model"
                or node["_meta"]["title"] == "Talemate Load Checkpoint"
            ):
                return node
        return None

    @property
    def reference_nodes(self) -> dict[str, dict]:
        reference_nodes = {}
        for node_id, node in self.nodes.items():
            if node["_meta"]["title"].startswith("Talemate Reference "):
                reference_nodes[node_id] = node
        return reference_nodes

    @property
    def max_references(self) -> int:
        if self._max_references is not None:
            return self._max_references
        return len(self.reference_nodes)

    @property
    def model_type(self) -> str:
        main_model_node = self.main_model_node
        if not main_model_node:
            return None
        if "ckpt_name" in main_model_node["inputs"]:
            return "checkpoint"
        elif "unet_name" in main_model_node["inputs"]:
            return "unet"

    @property
    def is_outdated(self) -> bool:
        file_mtime = Path(self.path).stat().st_mtime
        return file_mtime > self.mtime

    @property
    def copy(self) -> "Workflow":
        return Workflow(**self.model_dump())

    def set_resolution(self, resolution: Resolution):
        resolution_node = self.resolution_node
        if not resolution_node:
            log.warning("set_resolution", error="No resolution node found")
            return
        resolution_node["inputs"]["width"] = resolution.width
        resolution_node["inputs"]["height"] = resolution.height

    def set_prompt(self, prompt: str, negative_prompt: str = None):
        positive_prompt_node = None
        negative_prompt_node = None

        positive_prompt_node = self.positive_prompt_node
        negative_prompt_node = self.negative_prompt_node

        if not positive_prompt_node:
            log.warning("set_prompt", error="No positive prompt node found")
            return

        if positive_prompt_node:
            if "text" in positive_prompt_node["inputs"]:
                positive_prompt_node["inputs"]["text"] = prompt
            elif "prompt" in positive_prompt_node["inputs"]:
                positive_prompt_node["inputs"]["prompt"] = prompt

        if negative_prompt_node and negative_prompt:
            if "text" in negative_prompt_node["inputs"]:
                negative_prompt_node["inputs"]["text"] = negative_prompt
            elif "prompt" in negative_prompt_node["inputs"]:
                negative_prompt_node["inputs"]["prompt"] = negative_prompt

    def set_main_model(self, model: str):
        main_model_node = self.main_model_node

        if model is None or model == "":
            return

        if not main_model_node:
            log.warning("set_main_model", error="No main model node found")
            return

        if "ckpt_name" in main_model_node["inputs"]:
            main_model_node["inputs"]["ckpt_name"] = model
        elif "unet_name" in main_model_node["inputs"]:
            main_model_node["inputs"]["unet_name"] = model
        else:
            log.warning(
                "set_main_model",
                error="Unknown model loader - expected input for 'ckpt_name' or 'unet_name'",
            )
            return

    def set_seeds(self):
        for node in self.nodes.values():
            for field in node.get("inputs", {}).keys():
                if field == "noise_seed":
                    node["inputs"]["noise_seed"] = random.randint(0, 999999999999999)
                if field == "seed":
                    node["inputs"]["seed"] = random.randint(0, 999999999999999)

    def set_reference_images(self, image_paths: list[str]):
        """
        Bind uploaded reference image paths to matching nodes titled
        "Talemate Reference N" (1-indexed) by setting their `inputs.image`.
        Then, disconnect any unpopulated reference nodes from the graph by
        clearing inputs in other nodes that directly reference them.
        """
        # Map all reference nodes using reference_nodes property: index -> (node_id, node)
        ref_nodes: dict[int, tuple[str, dict]] = {}
        for node_id, node in self.reference_nodes.items():
            meta = node.get("_meta", {})
            title = meta.get("title")
            try:
                idx = int(str(title).split(" ")[-1])
            except Exception:
                continue
            ref_nodes[idx] = (str(node_id), node)

        log.debug(
            "workflow.set_reference_images.start",
            provided=len(image_paths) if image_paths else 0,
            total_refs=len(ref_nodes),
        )

        populated_indices: set[int] = set()
        # Assign provided images to corresponding reference nodes (1-indexed)
        for index, image_path in enumerate(image_paths or [], start=1):
            node_tuple = ref_nodes.get(index)
            if not node_tuple:
                log.debug(
                    "workflow.set_reference_images.missing_node",
                    title=f"Talemate Reference {index}",
                    image=image_path,
                )
                continue
            _node_id, node = node_tuple
            if "inputs" in node and "image" in node["inputs"]:
                node["inputs"]["image"] = image_path
                populated_indices.add(index)
                log.debug(
                    "workflow.set_reference_images.updated",
                    title=f"Talemate Reference {index}",
                    image=image_path,
                )
            else:
                log.debug(
                    "workflow.set_reference_images.no_image_input",
                    title=f"Talemate Reference {index}",
                )

        # Disconnect unpopulated reference nodes
        unpopulated_ids: set[str] = set()
        for idx, (node_id, _node) in ref_nodes.items():
            if idx not in populated_indices:
                unpopulated_ids.add(str(node_id))

        if unpopulated_ids:
            log.debug(
                "workflow.set_reference_images.disconnecting",
                count=len(unpopulated_ids),
                node_ids=list(unpopulated_ids),
            )
            for target_node_id, target_node in self.nodes.items():
                inputs = target_node.get("inputs", {})
                for input_key, input_value in list(inputs.items()):
                    # Remove direct single connections [node_id, socket_idx]
                    if (
                        isinstance(input_value, list)
                        and len(input_value) == 2
                        and str(input_value[0]) in unpopulated_ids
                    ):
                        del inputs[input_key]
                        log.debug(
                            "workflow.set_reference_images.disconnected",
                            target_node_id=str(target_node_id),
                            input_key=input_key,
                            from_node_id=str(input_value[0]),
                        )


@backends.register
class Backend(backends.Backend):
    name = BACKEND_NAME
    label = "ComfyUI"
    image_create = True
    image_edit = True
    image_analyzation = False
    description = "ComfyUI is a text to image and image editing backend."

    api_url: str
    workflow: Workflow | None = None

    _object_info: dict = pydantic.PrivateAttr(default={})
    _models: Models | None = None

    @property
    def generate_timeout(self) -> int:
        return get_agent("visual").generate_timeout

    @property
    def instance_label(self) -> str:
        return self.api_url

    @property
    async def object_info(self) -> dict:
        if self._object_info:
            return self._object_info

        log.debug("ComfyUI - Getting object info", api_url=self.api_url)
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url=f"{normalize_api_url(self.api_url)}/object_info"
            )
            self._object_info = response.json()

        return self._object_info

    @property
    async def models(self) -> Models:
        if self._models:
            return self._models
        try:
            info = await self.object_info
        except Exception as e:
            log.error("Failed to get object info", error=str(e), api_url=self.api_url)
            return Models()
        self._models = Models.from_info(info)
        return self._models

    @property
    def max_references(self) -> int:
        if self.workflow:
            return self.workflow.max_references
        return 0

    @property
    def generator_label(self) -> str | None:
        if self.workflow and self.workflow.path:
            # Return workflow filename without extension
            return Path(self.workflow.path).stem
        return None

    def _reload_workflow_if_outdated(self):
        """Reload workflow from disk if it's outdated."""
        if self.workflow and self.workflow.is_outdated:
            workflow_filename = Path(self.workflow.path).name
            workflow_path = WORKFLOW_DIR / workflow_filename
            if workflow_path.exists():
                log.debug(
                    "Reloading outdated workflow",
                    workflow_filename=workflow_filename,
                    workflow_path=workflow_path,
                )
                with open(workflow_path, "r", encoding="utf-8") as f:
                    self.workflow = Workflow(
                        nodes=json.load(f),
                        path=str(workflow_path),
                        mtime=workflow_path.stat().st_mtime,
                    )
                # Update cache
                WORKFLOW_CACHE[workflow_filename] = self.workflow

    async def ready(self) -> backends.BackendStatus:
        try:
            # Ensure one non-blocking connection probe, with status updated via callback
            await self.ensure_test_connection_task()

            if self.status.type == backends.BackendStatusType.OK:
                await self.models
        except Exception as e:
            self.status = backends.BackendStatus(
                type=backends.BackendStatusType.ERROR, message=str(e)
            )

        if self.status.type == backends.BackendStatusType.OK:
            # Reload workflow if it's outdated
            self._reload_workflow_if_outdated()

            # ensure workflow has ANY reference nodes
            if not self.workflow:
                self.status = backends.BackendStatus(
                    type=backends.BackendStatusType.ERROR,
                    message="no workflow selected",
                )
                log.warning("no workflow selected", api_url=self.api_url)
            elif not self.workflow.positive_prompt_node:
                self.status = backends.BackendStatus(
                    type=backends.BackendStatusType.ERROR,
                    message="workflow missing required 'Talemate Positive Prompt' node",
                )
                log.warning(
                    "workflow missing required 'Talemate Positive Prompt' node",
                    api_url=self.api_url,
                )
            elif (
                not self.workflow.max_references
                and self.gen_type == GEN_TYPE.IMAGE_EDIT
            ):
                self.status = backends.BackendStatus(
                    type=backends.BackendStatusType.WARNING,
                    message="no reference nodes found in workflow",
                )
                log.warning(
                    "no reference nodes found in workflow", api_url=self.api_url
                )

        return self.status

    async def test_connection(self, timeout: int = 2) -> backends.BackendStatus:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url=f"{normalize_api_url(self.api_url)}/system_stats",
                    timeout=timeout,
                )
                ready = response.status_code == 200
                return backends.BackendStatus(
                    type=backends.BackendStatusType.OK
                    if ready
                    else backends.BackendStatusType.ERROR
                )
        except httpx.RequestError as e:
            log.error(
                "Failed to test connection to ComfyUI",
                error=str(e),
                api_url=self.api_url,
                timeout=timeout,
            )
            return backends.BackendStatus(
                type=backends.BackendStatusType.ERROR, message=str(e)
            )

    async def get_history(self, prompt_id: str):
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url=f"{normalize_api_url(self.api_url)}/history/{prompt_id}"
            )
            return response.json()

    async def get_image(self, filename: str, subfolder: str, folder_type: str):
        data = {"filename": filename, "subfolder": subfolder, "type": folder_type}
        url_values = urllib.parse.urlencode(data)

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url=f"{normalize_api_url(self.api_url)}/view?{url_values}"
            )
            return response.content

    async def get_images(self, prompt_id: str, max_wait: int | None = None):
        output_images = {}
        history = {}

        if max_wait is None:
            max_wait = self.generate_timeout

        start = time.time()

        while not history:
            log.info(
                "comfyui_get_images", waiting_for_history=True, prompt_id=prompt_id
            )
            history = await self.get_history(prompt_id)
            await asyncio.sleep(1.0)
            if time.time() - start > max_wait:
                raise TimeoutError("Max wait time exceeded")

        for node_id, node_output in history[prompt_id]["outputs"].items():
            if "images" in node_output:
                images_output = []
                for image in node_output["images"]:
                    image_data = await self.get_image(
                        image["filename"], image["subfolder"], image["type"]
                    )
                    images_output.append(image_data)
            output_images[node_id] = images_output

        return output_images

    async def upload_image(
        self,
        image_bytes: bytes,
        filename: str,
        mime: str = "image/png",
        subfolder: str = "talemate",
        folder_type: str = "input",
        overwrite: bool = True,
    ) -> dict:
        log.debug(
            "comfyui.upload_image.start",
            filename=filename,
            subfolder=subfolder,
            type=folder_type,
            overwrite=overwrite,
            size=len(image_bytes) if image_bytes is not None else None,
        )
        files = {
            "image": (filename, image_bytes, mime),
        }
        data = {
            "type": folder_type,
            "subfolder": subfolder,
            "overwrite": str(overwrite).lower(),
        }
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{normalize_api_url(self.api_url)}/upload/image",
                files=files,
                data=data,
            )
            r.raise_for_status()
            out = r.json()
            out.setdefault("name", filename)
            out.setdefault("subfolder", subfolder)
            out.setdefault("type", folder_type)
            out["reused"] = False
            log.debug(
                "comfyui.upload_image.done",
                name=out.get("name"),
                subfolder=out.get("subfolder"),
                type=out.get("type"),
            )
            return out

    async def generate(
        self, request: GenerationRequest, response: GenerationResponse
    ) -> bytes:
        model: str = request.agent_config["model"]
        workflow: Workflow = request.agent_config["workflow"].copy
        workflow.set_resolution(request.resolution)
        workflow.set_prompt(request.prompt, request.negative_prompt)
        workflow.set_main_model(model)
        workflow.set_seeds()

        # Inject reference images for image edit workflows
        reference_bytes = request.reference_bytes
        if request.gen_type == GEN_TYPE.IMAGE_EDIT and reference_bytes:
            log.debug(
                "comfyui.references.start",
                num_assets=len(request.reference_assets),
                has_inline_reference=bool(request.inline_reference),
                total_bytes=len(reference_bytes),
            )
            uploaded_paths: list[str] = []
            # Create a list of identifiers for each reference (asset_id for saved assets, None for inline)
            reference_ids = []
            if request.inline_reference:
                # Inline reference is always first in reference_bytes
                reference_ids.append(None)
            # Add asset IDs for saved assets
            reference_ids.extend(request.reference_assets)

            for idx, img_bytes in enumerate(reference_bytes):
                if not img_bytes:
                    asset_id = reference_ids[idx] if idx < len(reference_ids) else None
                    log.debug(
                        "comfyui.reference.skip_empty", asset_id=asset_id, index=idx
                    )
                    continue

                # Generate filename: use asset_id for saved assets, generate unique name for inline
                asset_id = reference_ids[idx] if idx < len(reference_ids) else None
                if asset_id:
                    filename = f"talemate_{asset_id[:10]}.png"
                else:
                    # Generate unique filename for inline reference
                    hash_str = hashlib.md5(img_bytes[:1024]).hexdigest()[:10]
                    filename = f"talemate_inline_{hash_str}.png"

                log.debug(
                    "comfyui.reference.upload",
                    asset_id=asset_id,
                    is_inline=asset_id is None,
                    filename=filename,
                    size=len(img_bytes),
                    index=idx,
                )
                uploaded = await self.upload_image(
                    image_bytes=img_bytes, filename=filename
                )
                image_name = uploaded.get("name", filename)
                subfolder = uploaded.get("subfolder", "talemate")
                image_path = f"{subfolder}/{image_name}" if subfolder else image_name
                uploaded_paths.append(image_path)
                log.debug("comfyui.reference.uploaded", path=image_path)
            log.debug(
                "comfyui.references.setting",
                count=len(uploaded_paths),
                paths=uploaded_paths,
            )
            workflow.set_reference_images(uploaded_paths)
        else:
            # disconnect all reference nodes which allows us to run qwen image
            # edit workflows to just generate image normally.
            workflow.set_reference_images([])

        payload = {"prompt": workflow.model_dump().get("nodes")}

        log.info(
            "comfyui.Backend.generate",
            payload=payload,
            api_url=self.api_url,
            request=request.model_dump(exclude={"inline_reference"}),
        )

        async with httpx.AsyncClient() as client:
            _response = await client.post(
                url=f"{normalize_api_url(self.api_url)}/prompt", json=payload
            )
            _response.raise_for_status()

        log.info("comfyui.Backend.generate", response=_response.text)

        r = _response.json()

        prompt_id = r["prompt_id"]

        images = await self.get_images(prompt_id)
        for node_id, node_images in images.items():
            for i, image in enumerate(node_images):
                # await self.emit_image(base64.b64encode(image).decode("utf-8"))
                # SAVE IMAGE TO FILE
                # with open(f'internal-comfyui-test-{node_id}-{i}.png', 'wb') as f:
                #     f.write(image)
                response.generated = image
                break

        return response

    async def cancel_request(self):
        """
        Cancel the current generation request by calling ComfyUI's /interrupt endpoint.
        """
        log.info("comfyui.Backend.cancel_request", api_url=self.api_url)
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url=f"{normalize_api_url(self.api_url)}/interrupt"
                )
                response.raise_for_status()
                log.info("comfyui.Backend.cancel_request", response=response.text)
        except Exception as e:
            log.error(
                "comfyui.Backend.cancel_request",
                error=str(e),
                api_url=self.api_url,
            )
            raise


class ComfyUIHandler(pydantic.BaseModel):
    backend: Backend
    action: AgentAction

    @property
    def api_url(self) -> str:
        return self.action.config["api_url"].value

    @property
    def workflow(self) -> str:
        return self.action.config["workflow"].value

    @property
    def model(self) -> str:
        return self.action.config["model"].value

    @property
    def resolution_square(self) -> Resolution:
        return Resolution(*self.action.config["resolution_square"].value)

    @property
    def resolution_portrait(self) -> Resolution:
        return Resolution(*self.action.config["resolution_portrait"].value)

    @property
    def resolution_landscape(self) -> Resolution:
        return Resolution(*self.action.config["resolution_landscape"].value)


class ComfyUIMixin:
    @classmethod
    def comfyui_shared_config(cls) -> dict[str, AgentActionConfig]:
        """
        Shared Agent configuration for comfyui actions
        """
        return {
            "api_url": AgentActionConfig(
                type="text",
                value="http://localhost:8188",
                label="API URL",
                description="The URL of the backend API",
                save_on_change=True,
            ),
            "workflow": AgentActionConfig(
                type="text",
                value="default-sdxl.json",
                label="Workflow",
                description="The workflow to use for comfyui (workflow file name inside ./templates/comfyui-workflows)",
                choices=[],
                save_on_change=True,
            ),
            "model": AgentActionConfig(
                type="autocomplete",
                value="",
                label="Model",
                choices=[],
                description="The main image generation model to use.",
            ),
            "prompt_type": AgentActionConfig(
                type="text",
                title="Prompt generation",
                value=PROMPT_TYPE.KEYWORDS,
                label="Prompting Type",
                choices=PROMPT_TYPE.choices(),
                description="The semantic style of the generated prompt. USe keywords for SDXL, SD51 and descriptive for flux and qwen.",
            ),
            "resolution_square": AgentActionConfig(
                type="vector2",
                title="Resolutions",
                value=[1024, 1024],
                label="Square",
                description="The resolution to use for the image generation.",
                choices=get_resolution_choices("square"),
            ),
            "resolution_portrait": AgentActionConfig(
                type="vector2",
                value=[832, 1216],
                label="Portrait",
                description="The resolution to use for the image generation.",
                choices=get_resolution_choices("portrait"),
            ),
            "resolution_landscape": AgentActionConfig(
                type="vector2",
                value=[1216, 832],
                label="Landscape",
                description="The resolution to use for the image generation.",
                choices=get_resolution_choices("landscape"),
            ),
        }

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["comfyui_image_create"] = AgentAction(
            enabled=True,
            container=True,
            icon="mdi-image",
            label="ComfyUI",
            subtitle="Text to image",
            description="Basic text to image generation configuration for ComfyUI.",
            condition=AgentActionConditional(
                attribute="_config.config.backend", value=BACKEND_NAME
            ),
            config=cls.comfyui_shared_config(),
        )

        actions["comfyui_image_edit"] = AgentAction(
            enabled=True,
            container=True,
            icon="mdi-image-edit",
            label="ComfyUI",
            subtitle="Image editing",
            description="Image editing configuration for ComfyUI.",
            condition=AgentActionConditional(
                attribute="_config.config.backend_image_edit", value=BACKEND_NAME
            ),
            config=cls.comfyui_shared_config(),
        )

        # default prompt_type for edit should be DESCRIPTIVE
        actions["comfyui_image_edit"].config[
            "prompt_type"
        ].value = PROMPT_TYPE.DESCRIPTIVE

        return actions

    ## helpers

    @property
    async def comfyui_workflows(self) -> list[str]:
        """
        Returns list of workflow files in the workflows directory
        """
        return [file.name for file in WORKFLOW_DIR.glob("*.json")]

    async def comfyui_get_model_type(self, handler: ComfyUIHandler) -> str | None:
        workflow_filename = handler.action.config["workflow"].value
        if not workflow_filename:
            return None
        workflow = await self.comfyui_load_workflow(workflow_filename)
        model_type = workflow.model_type if workflow else None
        return model_type

    async def comfyui_load_workflow(self, workflow_filename: str) -> Workflow | None:
        _loaded_workflow: Workflow | None = WORKFLOW_CACHE.get(workflow_filename)
        workflow_path = WORKFLOW_DIR / workflow_filename

        if _loaded_workflow and not _loaded_workflow.is_outdated:
            log.debug(
                "Using cached workflow",
                workflow_filename=workflow_filename,
                workflow_path=workflow_path,
            )
            return _loaded_workflow

        if not workflow_path.exists():
            raise FileNotFoundError(f"Workflow file `{workflow_path}` not found")

        with open(workflow_path, "r", encoding="utf-8") as f:
            log.debug(
                "Loading workflow",
                workflow_filename=workflow_filename,
                workflow_path=workflow_path,
            )
            _loaded_workflow = Workflow(
                nodes=json.load(f),
                path=str(workflow_path),
                mtime=workflow_path.stat().st_mtime,
            )
            WORKFLOW_CACHE[workflow_filename] = _loaded_workflow
            return _loaded_workflow

    def comfyui_handler(self, backend_type: str) -> ComfyUIHandler | None:
        if (
            backend_type == "backend"
            and self.backend
            and isinstance(self.backend, Backend)
        ):
            return ComfyUIHandler(
                backend=self.backend, action=self.actions["comfyui_image_create"]
            )
        elif (
            backend_type == "backend_image_edit"
            and self.backend_image_edit
            and isinstance(self.backend_image_edit, Backend)
        ):
            return ComfyUIHandler(
                backend=self.backend_image_edit,
                action=self.actions["comfyui_image_edit"],
            )
        return None

    @property
    def comfyui_handlers(self) -> list[ComfyUIHandler]:
        return [
            self.comfyui_handler("backend"),
            self.comfyui_handler("backend_image_edit"),
        ]

    ## status

    async def _comfyui_emit_status(self, processing: bool = None):
        workflows = await self.comfyui_workflows
        for handler in self.comfyui_handlers:
            if not handler:
                continue
            handler.action.config["workflow"].choices = [
                {"label": workflow, "value": workflow} for workflow in workflows
            ]
            # Ensure backend status is up to date by calling ready()
            await handler.backend.ready()
            model_type = await self.comfyui_get_model_type(handler)
            log.debug("comfyui_emit_status", model_type=model_type)
            models = await handler.backend.models
            handler.action.config["model"].choices = models.get_choices(model_type)

    async def comfyui_emit_status(self, processing: bool = None):
        task = getattr(self, "_comfyui_emit_status_task", None)
        if task and not task.done():
            return
        self._comfyui_emit_status_task = asyncio.create_task(
            self._comfyui_emit_status(processing)
        )

    ## backend instantiation / swapping

    async def _comfyui_backend(
        self,
        backend: Backend | None,
        action_name: str,
        old_config: dict | None = None,
        force: bool = False,
    ) -> Backend | None:
        backend_instance_exists = isinstance(backend, Backend)
        api_url = self.actions[action_name].config["api_url"].value
        workflow = self.actions[action_name].config["workflow"].value

        gen_type = (
            GEN_TYPE.TEXT_TO_IMAGE
            if action_name == "comfyui_image_create"
            else GEN_TYPE.IMAGE_EDIT
        )
        prompt_type = self.actions[action_name].config["prompt_type"].value

        try:
            _api_url_changed = (
                old_config[action_name].config["api_url"].value != api_url
            )
        except KeyError:
            _api_url_changed = False

        try:
            _workflow_changed = (
                old_config[action_name].config["workflow"].value != workflow
            )
        except KeyError:
            _workflow_changed = False

        _reinit = force or _api_url_changed or not backend_instance_exists

        if _workflow_changed:
            # unset model selection
            self.actions[action_name].config["model"].value = ""

        workflow_instance = await self.comfyui_load_workflow(workflow)

        if _reinit:
            log.debug(
                "reinitializing comfyui backend",
                action_name=action_name,
                api_url=api_url,
                gen_type=gen_type,
                prompt_type=prompt_type,
            )
            return Backend(
                api_url=api_url,
                workflow=workflow_instance,
                gen_type=gen_type,
                prompt_type=prompt_type,
            )

        backend.workflow = workflow_instance
        backend.prompt_type = prompt_type
        return backend

    async def comfyui_backend(
        self, old_config: dict | None = None, force: bool = False
    ) -> Backend:
        return await self._comfyui_backend(
            self.backend, "comfyui_image_create", old_config, force
        )

    async def comfyui_backend_image_edit(
        self, old_config: dict | None = None, force: bool = False
    ) -> Backend:
        return await self._comfyui_backend(
            self.backend_image_edit, "comfyui_image_edit", old_config, force
        )

    ## generation

    async def comfyui_prepare_generation(self, request: GenerationRequest) -> Backend:
        workflow = None
        handler = None
        model = None
        if request.gen_type == GEN_TYPE.TEXT_TO_IMAGE:
            handler = self.comfyui_handler("backend")
        elif request.gen_type == GEN_TYPE.IMAGE_EDIT:
            handler = self.comfyui_handler("backend_image_edit")

        if not handler:
            raise ValueError(f"Invalid generation type: {request.gen_type}")

        workflow = await self.comfyui_load_workflow(handler.workflow)
        model = handler.model

        request.agent_config["workflow"] = workflow
        request.agent_config["model"] = model
        request.resolution = self.resolution(request.format, handler.action)

        return handler.backend
