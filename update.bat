@echo off
REM update.bat - Update script for Talemate with uv

REM Check if uv is installed
where uv >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo uv is not installed. Please install uv first: https://github.com/astral-sh/uv
    exit /b 1
)

REM check if we are inside a git checkout
if not exist .git (
git init
git remote add origin https://github.com/vegu-ai/talemate
)

REM pull the latest changes from git repository
git pull

REM install dependencies with uv
echo Updating virtual environment...
uv pip install -e ".[dev]"

echo Virtual environment updated!

REM updating npm packages
echo Updating npm packages...
cd talemate_frontend
npm install

REM build the frontend
echo Building frontend...
npm run build

cd ..

echo Update complete!