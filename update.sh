#!/bin/bash

# check if we are inside a git checkout
if [ ! -d ".git" ]; then
    git init
    git remote add origin https://github.com/vegu-ai/talemate
fi

# Pull latest changes
git pull

# Install dependencies with uv
echo "Updating virtual environment..."
uv pip install -e ".[dev]"

echo "Virtual environment updated!"

# Update frontend packages
echo "Updating frontend packages..."

# use the portable Node.js provisioned by install.sh (falls back to system Node)
source install-utils/node-env.sh
activate_embedded_node

cd talemate_frontend

# pnpm is provisioned on demand via corepack (bundled with Node.js); the
# version is pinned by the "packageManager" field in package.json.
export COREPACK_ENABLE_DOWNLOAD_PROMPT=0
corepack pnpm install --frozen-lockfile

# Build frontend
echo "Building frontend..."
corepack pnpm build

cd ..

echo "Update complete!"