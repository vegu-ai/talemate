## Quick install instructions

### Dependencies

--8<-- "docs/snippets/common.md:python-versions"

1. node.js and npm - see instructions [here](https://nodejs.org/en/download/package-manager/)
1. python- see instructions [here](https://www.python.org/downloads/)
1. uv - see instructions [here](https://github.com/astral-sh/uv#installation)

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

1. Navigate to the `talemate_frontend` directory.
2. If you haven't already, install npm dependencies by running `npm install`.
3. Start the server with `npm run serve`.

Please note that you may need to set environment variables or modify the host and port as per your setup. You can refer to the various start scripts for more details.