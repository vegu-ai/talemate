@echo off

echo Checking git repository...
REM check if git repository is initialized and initialize if not
if not exist .git (
git init
git remote add origin https://github.com/vegu-ai/talemate
)

REM pull the latest changes from git repository
git pull

REM activate the virtual environment
call talemate_env\Scripts\activate

REM use poetry to install dependencies
echo Updating virtual environment...
python -m poetry install

REM we use nvcc to check for CUDA availability
REM if cuda exists: pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
nvcc --version >nul 2>&1

IF ERRORLEVEL 1 (
    echo CUDA not found. Keeping PyTorch installation without CUDA support...
) ELSE (
    echo CUDA found. Installing PyTorch with CUDA support...
    REM uninstalling existing torch, torchvision, torchaudio
    python -m pip uninstall torch torchaudio -y
    python -m pip install torch~=2.4.1 torchaudio~=2.4.1 --index-url https://download.pytorch.org/whl/cu121
)

echo Virtual environment updated!

REM updating npm packages
echo Updating npm packages...
cd talemate_frontend
call npm install

echo NPM packages updated

REM build the frontend
echo Building frontend...
call npm run build

cd ..
echo Update complete - You may close this window now.
pause