## Quick install instructions

### Dependencies

--8<-- "docs/snippets/common.md:python-versions"

1. python - see instructions [here](https://www.python.org/downloads/)
1. uv - see instructions [here](https://github.com/astral-sh/uv#installation)

`install.sh` downloads a portable Node.js 22 runtime automatically (used to build the frontend), so you do not need to install Node.js yourself.

### Installation

1. `git clone https://github.com/vegu-ai/talemate.git`
1. `cd talemate`
1. `source install.sh`
    - When asked if you want to install pytorch with CUDA support choose `y` if you have
        a CUDA compatible Nvidia GPU and have installed the necessary drivers.
1. `source start.sh`

If everything went well, you can proceed to [connect a client](../../connect-a-client).

## Additional Information

### Setting Up a Virtual Environment

1. Open a terminal.
2. Navigate to the project directory.
3. uv will automatically create a virtual environment when you run `uv venv`.

### Installing Dependencies

1. Use uv to install dependencies by running `uv pip install -e ".[dev]"`.

### Running the Backend

1. You can start the backend server using `uv run src/talemate/server/run.py runserver --host 0.0.0.0 --port 5050`.

### Running the Frontend

Unlike the quick install above, this manual path does not provision Node.js for you — install Node.js 22+ yourself (see [here](https://nodejs.org/en/download/package-manager/)). Corepack ships with it and provides `pnpm`.

1. Navigate to the `talemate_frontend` directory.
2. If you haven't already, install frontend dependencies by running `corepack pnpm install`.
3. Start the server with `corepack pnpm run serve`.

Please note that you may need to set environment variables or modify the host and port as per your setup. You can refer to the various start scripts for more details.