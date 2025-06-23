#!/bin/sh

echo "Checking git repository..."
# Initialize git if needed
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

echo "NPM packages updated"

# Build frontend
echo "Building frontend..."
npm run build

cd ..
echo "Update complete"