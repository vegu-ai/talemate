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

# navigate to the frontend directory
echo "Updating the frontend..."
cd talemate_frontend
npm install

# build the frontend
echo "Building the frontend..."
npm run build

# return to the root directory
cd ..

echo "Installation completed successfully."
read -p "Press [Enter] key to continue..."
