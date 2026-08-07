#!/bin/bash

# create a virtual environment with uv
echo "Creating a virtual environment with uv..."
uv venv

# activate the virtual environment
echo "Activating the virtual environment..."
source .venv/bin/activate

# install dependencies with uv
echo "Installing dependencies..."
uv pip install -e ".[dev]"

# copy config.example.yaml to config.yaml only if config.yaml doesn't exist
if [ ! -f config.yaml ]; then
    echo "Copying config.example.yaml to config.yaml..."
    cp config.example.yaml config.yaml
fi

# provision a portable Node.js runtime (pnpm 11 needs Node >= 22.13)
echo "Setting up the Node.js runtime..."
source install-utils/node-env.sh
if ! install_embedded_node; then
    echo "ERROR: could not provision Node.js. Aborting installation."
    return 1 2>/dev/null || exit 1
fi

# navigate to the frontend directory
echo "Updating the frontend..."
cd talemate_frontend

# pnpm is provisioned on demand via corepack (bundled with Node.js); the
# version is pinned by the "packageManager" field in package.json.
export COREPACK_ENABLE_DOWNLOAD_PROMPT=0
corepack pnpm install --frozen-lockfile

# build the frontend
echo "Building the frontend..."
corepack pnpm build

# return to the root directory
cd ..

echo "Installation completed successfully."
read -p "Press [Enter] key to continue..."
