@echo off

REM activate the virtual environment
call talemate_env\Scripts\activate

REM use poetry to install dependencies
python -m poetry install

echo Virtual environment updated
pause
