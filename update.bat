@echo off

echo Checking git repository...
REM check if git repository is initialized and initialize if not
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
call npm install

echo NPM packages updated

REM build the frontend
echo Building frontend...
call npm run build

cd ..
echo Update complete - You may close this window now.
pause