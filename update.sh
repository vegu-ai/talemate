#!/bin/sh

echo "Checking git repository..."
# Initialize git if needed
if [ ! -d ".git" ]; then
    git init
    git remote add origin https://github.com/vegu-ai/talemate
fi

# Pull latest changes
git pull

# Activate virtual environment
. talemate_env/bin/activate

# Install dependencies with poetry
echo "Updating virtual environment..."
python -m poetry install

# Check for CUDA
if command -v nvcc >/dev/null 2>&1; then
    echo "CUDA found. Installing PyTorch with CUDA support..."
    python -m pip uninstall torch torchaudio -y
    python -m pip install torch~=2.4.1 torchaudio~=2.4.1 --index-url https://download.pytorch.org/whl/cu121
else
    echo "CUDA not found. Keeping PyTorch installation without CUDA support..."
fi

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