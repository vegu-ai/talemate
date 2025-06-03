#!/bin/bash

# activate the virtual environment
source talemate_env/bin/activate

# uninstall torch and torchaudio
python -m pip uninstall torch torchaudio -y

# install torch and torchaudio
python -m pip install torch~=2.7.0 torchaudio~=2.7.0 --index-url https://download.pytorch.org/whl/cu128 