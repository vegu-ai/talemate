# Common issues

## Windows

### Frontend fails with errors

- ensure none of the directories leading to your talemate directory have special characters in them, this can cause issues with the frontend. so no `(1)` in the directory name.

## Docker

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