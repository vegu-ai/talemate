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

# Update npm packages
echo "Updating npm packages..."
cd talemate_frontend
npm install

# Build frontend
echo "Building frontend..."
npm run build

cd ..

echo "Update complete!"