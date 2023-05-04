#!/bin/bash

# create a virtual environment
python -m venv talemate_env

# activate the virtual environment
source talemate_env/bin/activate

# install poetry
pip install poetry

# use poetry to install dependencies
poetry install

# copy config.example.yaml to config.yaml only if config.yaml doesn't exist
if [ ! -f config.yaml ]; then
    cp config.example.yaml config.yaml
fi

# navigate to the frontend directory
cd talemate_frontend
npm install

# return to the root directory
cd ..

echo "Installation completed successfully."
read -p "Press [Enter] key to continue..."
