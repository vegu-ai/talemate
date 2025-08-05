## Quick install instructions

1. `git clone https://github.com/vegu-ai/talemate.git`
1. `cd talemate`
1. copy config file
    1. linux: `cp config.example.yaml config.yaml` 
    1. windows: `copy config.example.yaml config.yaml` (or just copy the file and rename it via the file explorer)
1. `docker compose up`
1. Navigate your browser to http://localhost:8080

!!! info "Pre-built Images"
    The default setup uses pre-built images from GitHub Container Registry that include CUDA support by default. To manually build the container instead, use `docker compose -f docker-compose.manual.yml up --build`.

!!! note
    When connecting local APIs running on the hostmachine (e.g. text-generation-webui), you need to use `host.docker.internal` as the hostname.
