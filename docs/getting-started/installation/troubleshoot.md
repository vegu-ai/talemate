# Common issues

## Windows

### Installation fails with "Microsoft Visual C++" or "ValueError: The onnxruntime python package is not installed." errors
    
If your installation errors with a notification to upgrade "Microsoft Visual C++" go to [https://visualstudio.microsoft.com/visual-cpp-build-tools/](https://visualstudio.microsoft.com/visual-cpp-build-tools/) and click "Download Build Tools" and run it.

-  During installation make sure you select the C++ development package (upper left corner)
-  Run `reinstall.bat` inside talemate directory

## Docker

### Docker has created `config.yaml` directory

If you do not copy the example config to `config.yaml` before running `docker compose up` docker will create a `config` directory in the root of the project. This will cause the backend to fail to start.

This happens because we mount the config file directly as a docker volume, and if it does not exist docker will create a directory with the same name.

This will eventually be fixed, for now please make sure to copy the example config file before running the docker compose command.

## General

### Running behind reverse proxy with ssl

Personally i have not been able to make this work yet, but its on my list, issue stems from some vue oddities when specifying the base urls while running in a dev environment. I expect once i start building the project for production this will be resolved.

If you do make it work, please reach out to me so i can update this documentation.