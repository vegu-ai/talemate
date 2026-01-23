# Debug Logging

By default, Talemate logs at the `INFO` level. To enable more verbose `DEBUG` logging, set the `TALEMATE_DEBUG` environment variable to `1` before starting the server.

This will output detailed debug information from all components, which is useful for troubleshooting issues or reporting bugs.

#### :material-linux: Linux

Prefix the start command with the environment variable:

```bash
TALEMATE_DEBUG=1 ./start.sh
```

Or if running manually:

```bash
TALEMATE_DEBUG=1 uv run src/talemate/server/run.py runserver --host 0.0.0.0 --port 5050
```

#### :material-microsoft-windows: Windows

Set the environment variable before running the start script:

```batch
SET TALEMATE_DEBUG=1
start.bat
```

## Disabling debug logging

To return to normal logging, unset the variable or set it to `0`:

#### :material-linux: Linux

```bash
unset TALEMATE_DEBUG
```

Or simply run without the prefix:

```bash
./start.sh
```

#### :material-microsoft-windows: Windows

```batch
SET TALEMATE_DEBUG=0
start.bat
```
