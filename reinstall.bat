@echo off

IF EXIST talemate_env rmdir /s /q "talemate_env"

REM create a virtual environment
python -m venv talemate_env

REM activate the virtual environment
call talemate_env\Scripts\activate

REM install poetry
python -m pip install poetry "rapidfuzz>=3" -U

REM use poetry to install dependencies
python -m poetry install

echo Virtual environment re-created.
pause
