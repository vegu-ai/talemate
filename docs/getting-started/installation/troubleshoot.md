# Common issues

## Windows

### Frontend fails with errors

- ensure none of the directories leading to your talemate directory have special characters in them, this can cause issues with the frontend. so no `(1)` in the directory name.

## Docker

### Docker cannot start with the NVIDIA device request

The default configuration requires both an NVIDIA GPU and a working NVIDIA Container Toolkit. If either is missing, Docker reports an error similar to:

```text
could not select device driver "nvidia" with capabilities: [[gpu]]
```

On a host without an NVIDIA GPU, start the CPU-only configuration instead:

```bash
docker compose -f docker-compose.cpu.yml up
```

If the host has an NVIDIA GPU, confirm `nvidia-smi` works on the host, then install or repair the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html). Verify the Toolkit before retrying Talemate:

```bash
docker run --rm --gpus all ubuntu nvidia-smi
```

### CUDA is not available in a running container

If the Toolkit probe succeeds and Talemate starts, check the running container:

```bash
docker compose exec talemate nvidia-smi
docker compose exec talemate /app/.venv/bin/python -B -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"
```

If `nvidia-smi` works inside Talemate but the Python command reports `False`, update the host NVIDIA driver to one compatible with the image's locked CUDA 12.8 build, then recreate the container.

To run without CUDA instead, use:

```bash
docker compose -f docker-compose.cpu.yml up
```

### Docker has created `config.yaml` directory

If you do not copy the example config to `config.yaml` before running `docker compose up` docker will create a `config` directory in the root of the project. This will cause the backend to fail to start.

This happens because we mount the config file directly as a docker volume, and if it does not exist docker will create a directory with the same name.

This will eventually be fixed, for now please make sure to copy the example config file before running the docker compose command.

### Configuring WebSocket URL at Runtime

If you need to connect the frontend to a backend running on a different host or port (e.g., behind a reverse proxy), you can configure this at container startup without rebuilding the image.

Set the `VITE_TALEMATE_BACKEND_WEBSOCKET_URL` environment variable:

```bash
# Using docker run
docker run -e VITE_TALEMATE_BACKEND_WEBSOCKET_URL=wss://api.example.com/ws ghcr.io/vegu-ai/talemate:latest

# Using docker-compose.yml
services:
  talemate:
    environment:
      - VITE_TALEMATE_BACKEND_WEBSOCKET_URL=wss://api.example.com/ws
```

**URL Format:**

- Use `ws://` for unencrypted connections
- Use `wss://` for SSL/TLS connections (required if behind HTTPS proxy)
- Include the `/ws` path suffix

**If not set**, the frontend automatically connects to `ws://<current-hostname>:5050/ws`.

## General

### Running behind reverse proxy with SSL

To run Talemate behind a reverse proxy with SSL:

1. Configure your reverse proxy to forward WebSocket connections to the backend (port 5050)
2. Set the WebSocket URL to use your proxy's public address:

```yaml
# docker-compose.yml
environment:
  - VITE_TALEMATE_BACKEND_WEBSOCKET_URL=wss://your-domain.com/ws
```

3. Ensure your proxy is configured to handle WebSocket upgrades. Example nginx config:

```nginx
location /ws {
    proxy_pass http://talemate:5050/ws;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
}
```
