# AUTOMATIC1111

!!! info
    This requires you to setup a local instance of the AUTOMATIC1111 API. Follow the instructions from [their GitHub](https://github.com/AUTOMATIC1111/stable-diffusion-webui) to get it running.

Once you have it running, you will want to adjust the `webui-user.bat` in the AUTOMATIC1111 directory to include the following command arguments:

```bat
set COMMANDLINE_ARGS=--api --listen --port 7861
```

Then run the `webui-user.bat` to start the API.

Once your AUTOAMTIC1111 API is running (check with your browser) you can set the Visualizer config to use the `AUTOMATIC1111` backend 

## Settings

![Visual agent automatic1111 settings](/talemate/img/0.27.0/automatic1111-settings.png)

##### API URL

The url of the API, if following this example, should be `http://localhost:7861`

##### Steps

The number of steps to use for image generation. More steps will result in higher quality images but will take longer to generate.

##### Sampling Method

Which sampling method to use for image generation. 

##### Schedule Type

Which scheduler to use for image generation.

##### CFG Scale

CFG scale for image generation.

##### Model type

Differentiates between `SD1.5` and `SDXL` models. This will dictate the resolution of the image generation and actually matters for the quality so make sure this is set to the correct model type for the model you are using.
