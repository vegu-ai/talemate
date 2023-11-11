@echo off

REM activate the virtual environment
call talemate_env\Scripts\activate

REM update dependencies from requirements.txt
python -m pip install -r requirements.txt --upgrade

echo Virtual environment re-created.
pause
