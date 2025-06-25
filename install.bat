@echo off
REM install.bat - Simplified installation script for Talemate with uv

REM Check if uv is installed
where uv >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo uv is not installed. Please install uv first: https://github.com/astral-sh/uv
    exit /b 1
)

REM create a virtual environment with uv
echo Creating a virtual environment with uv...
uv venv

REM install dependencies with uv
echo Installing dependencies...
uv pip install -e ".[dev]"

REM copy config.example.yaml to config.yaml only if config.yaml doesn't exist
if not exist config.yaml copy config.example.yaml config.yaml

REM navigate to the frontend directory
cd talemate_frontend

REM install frontend dependencies
echo Installing frontend dependencies...
npm install

REM build the frontend
echo Building frontend...
npm run build

cd ..

echo Installation complete!