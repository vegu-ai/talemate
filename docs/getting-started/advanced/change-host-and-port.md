# Changing host and port

## Backend

By default, the backend listens on `localhost:5050`.

To run the server on a different host and port, you need to change the values passed to the `--host` and `--port` parameters during startup and also make sure the frontend knows the new values.

### Changing the host and port for the backend

#### :material-linux: Linux

Copy `start.sh` to `start_custom.sh` and edit the `--host` and `--port` parameters.

```bash
#!/bin/sh
uv run src/talemate/server/run.py runserver --host 0.0.0.0 --port 1234
```

#### :material-microsoft-windows: Windows

Copy `start.bat` to `start_custom.bat` and edit the `--host` and `--port` parameters.

```batch
uv run src\talemate\server\run.py runserver --host 0.0.0.0 --port 1234
```

### Letting the frontend know about the new host and port

Copy `talemate_frontend/example.env.development.local` to `talemate_frontend/.env.production.local` and edit the `VITE_TALEMATE_BACKEND_WEBSOCKET_URL`.

```env
VITE_TALEMATE_BACKEND_WEBSOCKET_URL=ws://localhost:1234
```

Next rebuild the frontend.

```bash
cd talemate_frontend
npm run build
```

### Start the backend and frontend

Start the backend and frontend as usual.

#### :material-linux: Linux

```bash
./start_custom.sh
```

#### :material-microsoft-windows: Windows

```batch
start_custom.bat
```

## Frontend

By default, the frontend listens on `localhost:8080`.

To change the frontend host and port, you need to change the values passed to the `--frontend-host` and `--frontend-port` parameters during startup.

### Changing the host and port for the frontend

#### :material-linux: Linux

Copy `start.sh` to `start_custom.sh` and edit the `--frontend-host` and `--frontend-port` parameters.

```bash
#!/bin/sh
uv run src/talemate/server/run.py runserver --host 0.0.0.0 --port 5055 \
--frontend-host localhost --frontend-port 8082
```

#### :material-microsoft-windows: Windows

Copy `start.bat` to `start_custom.bat` and edit the `--frontend-host` and `--frontend-port` parameters.

```batch
uv run src\talemate\server\run.py runserver --host 0.0.0.0 --port 5055 --frontend-host localhost --frontend-port 8082
```

### Start the backend and frontend

Start the backend and frontend as usual.

#### :material-linux: Linux

```bash
./start_custom.sh
```

#### :material-microsoft-windows: Windows

```batch
start_custom.bat
```