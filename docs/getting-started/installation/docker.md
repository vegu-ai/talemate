!!! example "Experimental"
    Talemate through docker has not received a lot of testing from me, so please let me know if you encounter any issues.
    
    You can do so by creating an issue on the [:material-github: GitHub repository](https://github.com/vegu-ai/talemate)

## Pre-built Images

Pre-built Docker images are automatically published to GitHub Container Registry for each release:

- **CPU version**: `ghcr.io/vegu-ai/talemate:latest`
- **CUDA version**: `ghcr.io/vegu-ai/talemate:latest-cuda`

### Using Pre-built Images

1. Create a `docker-compose.yml` file:
```yaml
version: '3.8'
services:
  talemate:
    image: ghcr.io/vegu-ai/talemate:latest  # or :latest-cuda for GPU support
    ports:
      - "8080:8080"
      - "5050:5050"
    volumes:
      - ./config.yaml:/app/config.yaml
      - ./scenes:/app/scenes
      - ./templates:/app/templates
      - ./chroma:/app/chroma
    environment:
      - PYTHONUNBUFFERED=1
```

2. Create your config file: `cp config.example.yaml config.yaml`
3. Run: `docker compose up`
4. Navigate to http://localhost:8080

## Building from Source

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
