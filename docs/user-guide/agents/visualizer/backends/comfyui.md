# ComfyUI

## Prepare ComfyUI

This document assumes you have installed ComfyUI (either the portable or the desktop version).

Copy the .bat file you use to start ComfyUI and add the `--port` parameter.

```
--port 8188
```

You can put any port you want, but this example will use 8188.


!!! note "If you are using a remote ComfyUI instance"
    If you are using a remote ComfyUI instance, you may want to add the `--listen` parameter as well.

    ```
    --listen 0.0.0.0
    ```

    You will then also need to obtain the IP address of the computer running ComfyUI and use it in the Talemate configuration. (instead of localhost)


Confirm ComfyUI is running in your browser by visiting http://localhost:8188 or `http://<ip-address>:8188` before proceeding to talemate.

## Talemate configuration

In the Visualizer agent settings, select ComfyUI as your backend for text-to-image generation, image editing, or both. You'll need to configure each backend separately if you want to use ComfyUI for different operations.

![The image displays the General settings tab of the Visualizer interface, featuring a sidebar with active indicators for ComfyUI and Google modules. Dropdown menus in the main panel show ComfyUI selected for text-to-image and image editing backends, with Google selected for image analysis. The interface also includes an image generation timeout slider set to 301 and an enabled Automatic Setup checkbox.](/talemate/img/0.34.0/visual-agent-comfyui-1.png)

### Text-to-Image Configuration

For text-to-image generation, configure the following settings:

- **API URL**: The URL where your ComfyUI instance is running (e.g., `http://localhost:8188`)
- **Workflow**: Select the workflow file to use for generation. Talemate includes several pre-configured workflows including `qwen_image.json` and `z_image_turbo.json`
- **Model**: Select the model to use from your ComfyUI models directory. If your workflow doesn't include a "Talemate Load Model" or "Talemate Load Checkpoint" node, this will be set to "- Workflow default -" and the model specified in the workflow file will be used.
- **Prompt Type**: Choose between "Keywords" or "Descriptive" prompt formatting

    !!! tip "Choosing Prompt Type"
        As a general rule: **SDXL models** typically work best with **Keywords** formatting, while most other models (including Qwen Image, Flux, etc.) work better with **Descriptive** formatting. If you're unsure, start with Descriptive and switch to Keywords if you're using an SDXL-based workflow.

- **Resolutions**: Configure the pixel dimensions for Square, Portrait, and Landscape formats

![A screenshot of the "Visualizer" application's dark-mode settings panel specifically for ComfyUI text-to-image generation. The interface features configuration fields for the API URL, a workflow dropdown set to "z_image_turbo.json," model selection, and a "Descriptive" prompting type. The lower section includes adjustable numeric inputs for defining pixel dimensions for Square, Portrait, and Landscape image resolutions.](/talemate/img/0.34.0/visual-agent-comfyui-2.png)
![This screenshot displays the dark-themed settings interface of an application named "Visualizer," specifically configured for ComfyUI text-to-image generation. The main panel features input fields for the API URL, workflow selection (set to default-sdxl), and model choice (juggernautXL), along with a prompting type setting. Below these options is a "Resolutions" section allowing users to define specific pixel dimensions for Square, Portrait, and Landscape image outputs.](/talemate/img/0.34.0/visual-agent-comfyui-3.png)

### Image Editing Configuration

For image editing, configure similar settings but select an image editing workflow such as `qwen_image_edit.json`. The number of reference images supported depends on your model - for example, Qwen Image Edit can handle up to 3 reference images that can be used to guide the editing process.

!!! note "Prompt Type for Image Editing"
    Image editing workflows typically use **Descriptive** prompt formatting by default, as most image editing models (like Qwen Image Edit) work better with descriptive instructions rather than keyword-based prompts.

![A screenshot of the "Visualizer" application settings interface, specifically showing the configuration panel for "ComfyUI Image Editing." The main view displays input fields for the API URL, a selected workflow file named "qwen_image_edit.json," descriptive prompting settings, and resolution presets for square, portrait, and landscape aspect ratios.](/talemate/img/0.34.0/visual-agent-comfyui-4.png)
![This screenshot shows a browser tab group labeled "Visualizer" marked with a green status dot on a dark background. The group contains four tabs: a Google link, two green-tinted ComfyUI tabs with image and pencil icons, and a gray tab titled "References 3".](/talemate/img/0.34.0/visual-agent-comfyui-5.png)


## Custom workflow creation

Talemate comes with pre-configured workflows for Qwen Image models (`qwen_image.json` for text-to-image and `qwen_image_edit.json` for image editing). However, since there are many variables in ComfyUI setups (different model formats like GGUF vs safetensors, custom LoRAs, different hardware configurations, etc.), you may want to customize these workflows to match your specific setup.

### Starting from a Template

Open ComfyUI in your browser and navigate to the templates menu. ComfyUI includes workflow templates that you can use as a starting point:

- **Qwen Image**: For text-to-image generation
- **Qwen Image Edit**: For image editing workflows

These templates provide a good foundation for creating custom workflows.

![A dark-themed dropdown menu from a software interface is shown, featuring a header labeled "image_qwen_image." The menu lists standard options such as New, File, Edit, View, and Theme, followed by specific actions like Browse Templates, Settings, Manage Extensions, and Help.](/talemate/img/0.34.0/comfyui.workflow.setup.browse-templates.png)

![A product card for the "Qwen-Image Text to Image" AI model, displaying a sample generation of a rainy, neon-lit street scene with vibrant pink and blue signage. The image demonstrates the model's capabilities by clearly rendering complex multilingual text, such as Chinese characters and English words like "HAPPY HAIR," on the storefronts. Below the visual, a brief description highlights the tool's exceptional text rendering and editing features.](/talemate/img/0.34.0/comfyui.workflow.setup.qwen-template.png)

Load the Qwen Image template to see the base workflow structure.

![A screenshot of a ComfyUI workflow designed for the Qwen-Image diffusion model, featuring grouped nodes for model loading, image sizing, and text prompting. The interface includes detailed instructional notes regarding VRAM usage on an RTX 4090D, model storage locations, and optimal KSampler settings. A positive prompt node is visible containing a detailed description of a neon-lit Hong Kong street scene.](/talemate/img/0.34.0/comfyui.workflow.setup.qwen-start.png)

### Naming Nodes for Talemate

For Talemate to properly interact with your workflow, you need to rename specific nodes with exact titles. These titles allow Talemate to inject prompts, set resolutions, and handle reference images automatically.

**Required Node Titles:**

1. **Talemate Positive Prompt**: The node that encodes the positive prompt (typically a `CLIPTextEncode` or `TextEncodeQwenImageEditPlus` node). This is required - workflows without this node will fail validation.
2. **Talemate Negative Prompt**: The node that encodes the negative prompt (same node types as above)
3. **Talemate Resolution**: The node that sets the image dimensions (typically an `EmptySD3LatentImage` or similar latent image node)

**Optional Node Titles:**

- **Talemate Load Model** or **Talemate Load Checkpoint**: If you want to allow model selection from Talemate's settings, rename your model loader node (typically `CheckpointLoaderSimple`, `UNETLoader`, or `UnetLoaderGGUF`) to one of these titles. If this node is not present, Talemate will use the model specified in the workflow file itself, and the model dropdown will show "- Workflow default -" as the only option.

To rename a node, right-click on it and select "Rename" or double-click the node title, then enter the exact title name.

![A screenshot of a node-based interface labeled "Step 3 - Prompt," featuring a green "Talemate Positive Prompt" node containing a detailed text description of a vibrant, neon-lit Hong Kong street scene. The text specifies a 1980s cinematic atmosphere and lists numerous specific shop signs in both Chinese and English. Below it, a dark red "Talemate Negative Prompt" node is visible but currently contains no text.](/talemate/img/0.34.0/comfyui.workflow.setup.talemate-prompts.png)

![This image displays a dark green interface node labeled "Talemate Positive Prompt," typical of a node-based editor like ComfyUI. It features a yellow input connection point for "clip" on the left, an orange output point for "CONDITIONING" on the right, and a large, dark text entry field in the center containing the placeholder word "text".](/talemate/img/0.34.0/comfyui.workflow.setup.talemate-empty-prompt.png)

![A screenshot of a dark gray interface node labeled "Talemate Resolution" with the identifier #58. It features configurable fields for width and height, both set to 1328, and a batch size of 1. The node has a single output connection point labeled "LATENT".](/talemate/img/0.34.0/comfyui.workflow.setup.talemate-resulotion.png)

### Activating the Lightning LoRA (Optional)

The Qwen Image template includes a Lightning LoRA node that is deactivated by default. You can optionally activate it to speed up generation with fewer steps. Note that this is a trade-off: the Lightning LoRA reduces generation time but may degrade image quality compared to using more steps without the LoRA.

To activate the Lightning LoRA:

1. Find the `LoraLoaderModelOnly` node in your workflow (it should already be present in the Qwen template)
2. Connect it between your model loader and sampler if it's not already connected
3. Load the appropriate Lightning LoRA file (e.g., `Qwen-Image-Lightning-8steps-V1.0.safetensors` for 8-step generation)
4. Adjust your sampler settings:

    - **Steps**: Reduce to 8 steps (or 4 steps for the 4-step variant)
    - **CFG Scale**: Set to 1.0 (lower than typical values)

![This screenshot features a "LoraLoaderModelOnly" node within a ComfyUI workflow, customized with the label "Lightx2v 8steps LoRA". It shows the selection of a "Qwen-Image-Lightning-8steps" LoRA file with a model strength parameter set to 1.00. Purple connection cables are visible attached to the input and output model terminals.](/talemate/img/0.34.0/comfyui.workflow.setup.lighting-lora.png)

![The image shows a close-up of a dark user interface panel containing two adjustable setting fields. The top field is labeled "steps" and displays a value of 8, flanked by left and right directional arrows. Below that, a second field labeled "cfg" shows a value of 1.0, also with adjustment arrows on either side.](/talemate/img/0.34.0/comfyui.workflow.setup.lighting-lora-sampler-changes.png)

### Image Editing Workflows: Reference Nodes

For image editing workflows (like `qwen_image_edit.json`), you need to add reference image nodes. Note that ComfyUI includes a Qwen Image Edit template similar to the Qwen Image template, which you can use as a starting point.

!!! warning "Reference Nodes Required"
    Image editing workflows **must** define at least one reference node. If your workflow doesn't include any nodes titled "Talemate Reference 1" (or higher), the backend status will show an error and image editing will not work.

These are `LoadImage` nodes that Talemate will use to inject reference images for editing.

The number of reference nodes you can add depends on your model's capabilities. For example, Qwen Image Edit supports up to 3 reference images. Add `LoadImage` nodes and rename them with these exact titles:

- **Talemate Reference 1**
- **Talemate Reference 2**
- **Talemate Reference 3** (if your model supports it)

These nodes should be connected to your prompt encoding nodes (for Qwen Image Edit, use `TextEncodeQwenImageEditPlus` nodes that accept image inputs).

![Three identical interface nodes labeled "Talemate Reference 1," "2," and "3" are arranged horizontally within a dark-themed node-based editor. Each node features output ports for "IMAGE" and "MASK," along with a file selection field showing "image_qwen_image_edit" and a "choose file to upload" button. Blue and red connection wires link these nodes to other off-screen elements in the workflow.](/talemate/img/0.34.0/comfyui.workflow.setup.talemate-references.png)

### Automatic Deactivation of Unused Reference Nodes

Talemate automatically handles situations where your workflow contains more reference nodes than you provide images for. When you run a generation:

- If you provide fewer reference images than the workflow supports, the unused reference nodes are automatically disconnected from the workflow graph
- If you provide no reference images at all, all reference nodes are disconnected

This means you can use a single image editing workflow for both text-to-image generation and image editing operations. For example, if you configure `qwen_image_edit.json` as your image editing backend:

- When you generate with reference images, those images are uploaded and connected to the appropriate reference nodes
- When you generate without reference images (pure text-to-image), all reference nodes are disconnected automatically, allowing the workflow to run as a standard text-to-image workflow

This behavior prevents errors that would otherwise occur if ComfyUI tried to process reference nodes without actual images loaded into them. You do not need to create separate workflows for text-to-image and image editing - a single workflow with reference nodes can serve both purposes, assuming the model supports it (qwen-image-edit 2511 seems to.)

### Saving and Exporting the Workflow

Once your workflow is configured, you need to save it and export it in the API format for Talemate to use it.

1. **Save the workflow**: Use File → Save As to save your workflow as a `.json` file in your ComfyUI workflows directory
2. **Export for API**: Use File → Export (API) to create the API-compatible version

!!! warning "Export vs Export (API)"
    It's critical to use **"Export (API)"** and not just "Export". The regular export format is not compatible with Talemate's API integration. The API export format includes the necessary metadata and structure that Talemate expects.

![A screenshot of a dark-themed software interface menu with the "File" option selected, revealing a nested sub-menu. The sub-menu lists file management commands, with the "Save As" option highlighted among choices like Open, Save, and Export.](/talemate/img/0.34.0/comfyui.workflow.setup.qwen-save.png)

![This image displays a dark-themed user interface menu, likely from ComfyUI, with the "File" category expanded. A submenu lists options including Open, Save, and Save As, while the "Export (API)" option is currently highlighted at the bottom. This visual illustrates how to locate the API export function within the software's file management system.](/talemate/img/0.34.0/comfyui.workflow.setup.qwen-export.png)

After exporting, place the workflow JSON file in Talemate's `templates/comfyui-workflows` directory. Once placed there, it will automatically appear in the workflow dropdown in Talemate's ComfyUI settings.

!!! note "Workflow File Location"
    Workflow files must be placed in Talemate's `templates/comfyui-workflows` directory, not ComfyUI's workflows directory. Talemate loads workflows from its own templates directory to ensure compatibility and proper integration.

!!! tip "Workflow Not Appearing?"
    If your workflow file doesn't appear in the agent's settings dropdown after placing it in the correct directory, try reloading the Talemate browser window. The workflow list is refreshed when the page loads.

!!! info "Hot-Reloading Workflows"
    Changes to workflow files are automatically detected and reloaded by the agent. After modifying a workflow file, your changes will be applied to the next image generation without needing to restart Talemate or reload the browser window.

