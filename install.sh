#!/bin/bash

# Function to check if a command exists
command_exists() {
  command -v "$1" >/dev/null 2>&1
}

# Install Python 3.9 using pyenv if not already available
if ! command_exists python3.9; then
  echo "Python 3.9 is not installed. Installing with pyenv..."

  # Check if pyenv is installed, install if not
  if ! command_exists pyenv; then
    echo "Installing pyenv..."
    curl https://pyenv.run | bash

    # Add pyenv to the shell (assuming bash)
    export PATH="$HOME/.pyenv/bin:$PATH"
    eval "$(pyenv init -)"
    eval "$(pyenv virtualenv-init -)"
  fi

  # Install build dependencies (example for Debian/Ubuntu, adapt for other distros)
  if command_exists apt-get; then #Debian, Ubuntu, Mint
      sudo apt-get update
      sudo apt-get install -y make build-essential libssl-dev zlib1g-dev \
      libbz2-dev libreadline-dev libsqlite3-dev wget curl llvm \
      libncursesw5-dev xz-utils tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev
  elif command_exists yum; then #RHEL, CentOs
      sudo yum update -y
      sudo yum groupinstall -y "Development Tools"
      sudo yum install -y openssl-devel bzip2-devel libffi-devel zlib-devel readline-devel sqlite-devel xz-devel
  elif command_exists dnf; then #Fedora
      sudo dnf update -y
      sudo dnf groupinstall -y "Development Tools"
      sudo dnf install -y openssl-devel bzip2-devel libffi-devel zlib-devel readline-devel sqlite-devel xz-devel
  elif command_exists zypper; then #openSUSE
    sudo zypper refresh
    sudo zypper install -y -t pattern devel_basis
    sudo zypper install -y libopenssl-devel libbz2-devel libffi-devel zlib-devel readline-devel sqlite3-devel xz-devel

  elif command_exists pacman; then # Arch Linux
    sudo pacman -Syu --needed base-devel openssl bzip2 libffi zlib readline sqlite xz

  else
      echo "Unsupported package manager. Please install build dependencies manually."
      exit 1
  fi


  pyenv install 3.9.18 # Or any other specific 3.9.x version
  pyenv global 3.9.18 # Set as the default pyenv Python
else
  echo "Python 3.9 is already installed."
fi

# create a virtual environment using Python 3.9
echo "Creating a virtual environment..."
pyenv exec python3.9 -m venv talemate_env

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
if [ "$cuda" == "y" ]; then
    echo "Installing PyTorch with CUDA support..."
    # uninstall torch and torchaudio
    pip uninstall torch torchaudio -y
    pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
fi

# copy config.example.yaml to config.yaml only if config.yaml doesn't exist
if [ ! -f "config.yaml" ]; then
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
