## Quick install instructions

1. Download the latest Talemate release ZIP from the [Releases page](https://github.com/vegu-ai/talemate/releases) and extract it anywhere on your system (for example, `C:\Talemate`).
2. Double-click **`start.bat`**.
   - On the very first run Talemate will automatically:
     1. Download a portable build of Python 3 and Node.js (no global installs required).
     2. Create and configure a Python virtual environment.
     3. Install all back-end and front-end dependencies with the included *uv* and *npm*.
     4. Build the web client.
3. When the console window prints **"Talemate is now running"** and the logo appears, open your browser at **http://localhost:8080**.

!!! note "First start can take a while"
    The initial download and dependency installation may take several minutes, especially on slow internet connections. The console will keep you updated – just wait until the Talemate logo shows up.

## Maintenance & advanced usage

| Script | Purpose |
|--------|---------|
| **`start.bat`** | Primary entry point – performs the initial install if needed and then starts Talemate. |
| **`install.bat`** | Runs the installer without launching the server. Useful for automated setups or debugging. |
| **`install-cuda.bat`** | Installs the CUDA-enabled Torch build (run after the regular install). |
| **`update.bat`** | Pulls the latest changes from GitHub, updates dependencies, rebuilds the web client. |

No system-wide Python or Node.js is required – Talemate uses the embedded runtimes it downloads automatically.