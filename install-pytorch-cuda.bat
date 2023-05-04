REM activate the virtual environment
call talemate_env\Scripts\activate

REM install pytouch+cuda
pip uninstall torch -y
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118