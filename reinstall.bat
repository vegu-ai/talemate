@echo off

IF EXIST talemate_env rmdir /s /q "talemate_env"

REM create a virtual environment
python -m venv talemate_env

REM activate the virtual environment
call talemate_env\Scripts\activate

REM install dependencies from requirements.txt
python -m pip install -r requirements.txt

echo Virtual environment re-created.
pause
