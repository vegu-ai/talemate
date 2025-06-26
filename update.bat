:0
@echo off

SETLOCAL ENABLEDELAYEDEXPANSION

REM Define fatal-error handler (copied from install.bat)
REM Usage: CALL :die "Message explaining what failed"
goto :after_die

:die
echo.
echo ============================================================
echo   !!! UPDATE FAILED !!!
echo   %*
echo ============================================================
pause
exit 1

:after_die

echo Checking git repository...
REM check if git repository is initialized and initialize if not
if not exist .git (
git init
git remote add origin https://github.com/vegu-ai/talemate
)

REM pull the latest changes from git repository
git pull

REM Check if .venv exists
IF NOT EXIST ".venv" (
    CALL :die ".venv directory not found. Please run install.bat first."
)

REM activate the virtual environment
call .venv\Scripts\activate

REM Check if embedded Python exists
IF NOT EXIST "embedded_python\python.exe" (
    CALL :die "embedded_python not found. Please run install.bat first."
)

REM ---------[ Use embedded Node.js ]---------
SET "NODE_DIR=embedded_node"
IF NOT EXIST "%NODE_DIR%\node.exe" (
    CALL :die "Embedded Node.js not found (expected at %CD%\%NODE_DIR%). Please run install.bat first."
)

REM Prepend embedded Node.js to PATH
SET "PATH=%CD%\%NODE_DIR%;%PATH%"
ECHO Using embedded Node.js at %CD%\%NODE_DIR%\node.exe

REM install dependencies with uv
echo Updating virtual environment...
embedded_python\python.exe -m uv sync || CALL :die "uv dependency sync failed."

echo Virtual environment updated!

REM updating npm packages
echo Updating npm packages...
cd talemate_frontend
call npm install || CALL :die "npm install failed."

echo NPM packages updated

REM build the frontend
echo Building frontend...
call npm run build || CALL :die "Frontend build failed."

cd ..
echo Update complete - You may close this window now.
pause