@echo off

REM check if git repository is initialized and initialize if not
if not exist .git (
git init
git remote add origin https://github.com/vegu-ai/talemate
)

REM pull the latest changes from git repository
git pull origin master

REM activate the virtual environment
call talemate_env\Scripts\activate

REM use poetry to install dependencies
python -m poetry install

echo Virtual environment updated
pause
