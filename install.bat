@echo off

REM Check for Python version and use a supported version if available
SET PYTHON=python
python -c "import sys; sys.exit(0 if sys.version_info[:2] in [(3, 10), (3, 11), (3, 12), (3, 13)] else 1)" 2>nul
IF NOT ERRORLEVEL 1 (
    echo Selected Python version: %PYTHON%
    GOTO EndVersionCheck
)

SET PYTHON=python
FOR /F "tokens=*" %%i IN ('py --list') DO (
    echo %%i | findstr /C:"-V:3.11 " >nul && SET PYTHON=py -3.11 && GOTO EndPythonCheck
    echo %%i | findstr /C:"-V:3.10 " >nul && SET PYTHON=py -3.10 && GOTO EndPythonCheck
)
:EndPythonCheck
%PYTHON% -c "import sys; sys.exit(0 if sys.version_info[:2] in [(3, 10), (3, 11), (3, 12), (3, 13)] else 1)" 2>nul
IF ERRORLEVEL 1 (
    echo Unsupported Python version. Please install Python 3.10 or 3.11.
    exit /b 1
)
IF "%PYTHON%"=="python" (
    echo Default Python version is being used: %PYTHON%
) ELSE (
    echo Selected Python version: %PYTHON%
)

:EndVersionCheck

IF ERRORLEVEL 1 (
    echo Unsupported Python version. Please install Python 3.10 or 3.11.
    exit /b 1
)

REM create a virtual environment with uv
uv venv

REM install dependencies with uv
uv pip install -e ".[dev]"

REM copy config.example.yaml to config.yaml only if config.yaml doesn't exist
IF NOT EXIST config.yaml copy config.example.yaml config.yaml

REM navigate to the frontend directory
echo Installing frontend dependencies...
cd talemate_frontend
call npm install

echo Building frontend...
call npm run build

REM return to the root directory
cd ..

echo Installation completed successfully.
pause
