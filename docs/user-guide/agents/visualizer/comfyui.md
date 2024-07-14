# ComfyUI

!!! info
    This requires you to setup a local instance of the ComfyUI API. Follow the instructions from their [GitHub](https://github.com/comfyanonymous/ComfyUI) to get it running.

Once you're setup, copy their `start.bat` file to a new `start-listen.bat` file and change the contents to.

```bat
call venv\Scripts\activate
call python main.py --port 8188 --listen 0.0.0.0
``` 

Then run the `start-listen.bat` to start the API.

Once your ComfyUI API is running (check with your browser) you can set the Visualizer config to use the `ComfyUI` backend.

## Settings

![Visual agent comfyui settings](/img/0.26.0/visual-agent-comfyui-settings.png)

##### API URL

The url of the API, if following this example, should be `http://localhost:8188`

##### Workflow

The workflow file to use. This is a comfyui api workflow file that needs to exist in `./templates/comfyui-workflows` inside the talemate directory. Talemate provides two very barebones workflows with `default-sdxl.json` and `default-sd15.json`. You can create your own workflows and place them in this directory to use them. 

!!! warning
    The workflow file must be generated using the API Workflow export, **not the UI export**. Please refer to their documentation for more information.

##### Checkpoint

The model to use - this will load a list of all available models in your comfyui instance. Select which one you want to use for the image generation.

!!! tip
    If your list of models is empty, try disabling and re-enabling the visualizer agent. This will force a refresh of the models list.

### Custom Workflows

When creating custom workflows for ideal compatibility with Talemate, ensure the following.

- A `CheckpointLoaderSimple` node named `Talemate Load Checkpoint`
- A `EmptyLatentImage` node name `Talemate Resolution`
- A `ClipTextEncode` node named `Talemate Positive Prompt`
- A `ClipTextEncode` node named `Talemate Negative Prompt`
- A `SaveImage` node at the end of the workflow.

![ComfyUI Base workflow example](/img/0.20.0/comfyui-base-workflow.png)