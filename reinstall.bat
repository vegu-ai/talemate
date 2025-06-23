@echo off

IF EXIST .venv rmdir /s /q ".venv"

REM create a virtual environment with uv
uv venv

REM install dependencies with uv
uv pip install -e ".[dev]"

echo Virtual environment re-created.
pause
