!!! example "Experimental"
    Talemate through docker has not received a lot of testing from me, so please let me know if you encounter any issues.
    
    You can do so by creating an issue on the [:material-github: GitHub repository](https://github.com/vegu-ai/talemate)

## Quick install instructions

1. `git clone https://github.com/vegu-ai/talemate.git`
1. `cd talemate`
1. copy config file
    1. linux: `cp config.example.yaml config.yaml` 
    1. windows: `copy config.example.yaml config.yaml`
1. If your host has a CUDA compatible Nvidia GPU
    1. Windows (via PowerShell): `$env:CUDA_AVAILABLE="true"; docker compose up`
    1. Linux: `CUDA_AVAILABLE=true docker compose up`
1. If your host does **NOT** have a CUDA compatible Nvidia GPU
    1. Windows: `docker compose up`
    1. Linux: `docker compose up`
1. Navigate your browser to http://localhost:8080

!!! note
    When connecting local APIs running on the hostmachine (e.g. text-generation-webui), you need to use `host.docker.internal` as the hostname.
