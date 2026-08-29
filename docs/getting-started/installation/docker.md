## Quick install instructions

1. `git clone https://github.com/vegu-ai/talemate.git`
1. `cd talemate`
1. copy config file
    1. linux: `cp config.example.yaml config.yaml` 
    1. windows: `copy config.example.yaml config.yaml` (or just copy the file and rename it via the file explorer)
1. Start Talemate:
    1. NVIDIA GPU host with the NVIDIA Container Toolkit installed: `docker compose up`
    1. Host without an NVIDIA GPU: `docker compose -f docker-compose.cpu.yml up`
1. Navigate your browser to http://localhost:8082

The default Compose configuration requires an NVIDIA GPU and the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html). It reserves all NVIDIA GPUs and does not fall back to CPU execution.

On a host without an NVIDIA GPU, you must use:

```bash
docker compose -f docker-compose.cpu.yml up
```

!!! info "Pre-built Images"
    The default setup uses a pre-built image from GitHub Container Registry. To build it locally with CUDA enabled, use `docker compose -f docker-compose.yml -f docker-compose.manual.yml up --build`. For a local CPU-only build, use the standalone command `docker compose -f docker-compose.manual.yml up --build`; combining `docker-compose.cpu.yml` and `docker-compose.manual.yml` is also supported.

## Verify CUDA access

With the container running, verify that Docker exposed the GPU and that PyTorch can use it:

```bash
docker compose exec talemate nvidia-smi
docker compose exec talemate /app/.venv/bin/python -B -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"
```

The final value from the Python command should be `True`. See [Common issues](troubleshoot.md#cuda-is-not-available-in-a-running-container) if either command fails.

!!! note
    When connecting local APIs running on the hostmachine (e.g. text-generation-webui), you need to use `host.docker.internal` as the hostname.

!!! info "Pi Bridge"
    The image ships with the [pi coding agent](../../user-guide/clients/types/pi-bridge.md) preinstalled for the Pi Bridge client. pi's configuration (`models.json`, `auth.json`) lives in the `./pi` directory next to the compose file.
