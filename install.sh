#!/bin/bash

# create a virtual environment
echo "Creating a virtual environment..."
python3 -m venv talemate_env

# activate the virtual environment
echo "Activating the virtual environment..."
source talemate_env/bin/activate

# install poetry
echo "Installing poetry..."
pip install poetry

# use poetry to install dependencies
echo "Installing dependencies..."
poetry install

# get input on whether to install torch with CUDA support
read -p "Do you want to install PyTorch with CUDA support? (y/n): " cuda

# install torch with CUDA support if the user wants to
# pip install torch~=2.4.1 torchaudio~=2.4.1 --index-url https://download.pytorch.org/whl/cu121
# if not, torch with cpu is alrady installed so nothing needs to be done
if [ $cuda == "y" ]; then
    echo "Installing PyTorch with CUDA support..."
    # uninstall torch and torchaudio
    pip uninstall torch torchaudio -y
    pip install torch~=2.7.0 torchaudio~=2.7.0 --index-url https://download.pytorch.org/whl/cu128
fi

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
