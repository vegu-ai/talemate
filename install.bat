@echo off

REM ===============================
REM  Talemate project installer
REM ===============================
REM 1. Detect CPU architecture and pick the best-fitting embedded Python build.
REM 2. Download & extract that build into .\embedded_python\
REM 3. Bootstrap pip via install-utils\get-pip.py
REM 4. Install virtualenv and create .\talemate_env\ using the embedded Python.
REM 5. Activate the venv and proceed with Poetry + frontend installation.
REM ---------------------------------------------------------------

SETLOCAL ENABLEDELAYEDEXPANSION

REM Define fatal-error handler
REM Usage: CALL :die "Message explaining what failed"
goto :after_die

:die
echo.
echo ============================================================
echo   !!! INSTALL FAILED !!!
echo   %*
echo ============================================================
pause
exit 1

:after_die

REM ---------[ Check Prerequisites ]---------
ECHO Checking prerequisites...
where tar >nul 2>&1 || CALL :die "tar command not found. Please ensure Windows 10 version 1803+ or install tar manually."
where curl >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    where bitsadmin >nul 2>&1 || CALL :die "Neither curl nor bitsadmin found. Cannot download files."
)

REM ---------[ Remove legacy Poetry venv if present ]---------
IF EXIST "talemate_env" (
    ECHO Detected legacy Poetry virtual environment 'talemate_env'. Removing...
    RD /S /Q "talemate_env"
    IF ERRORLEVEL 1 (
        ECHO [WARNING] Failed to fully remove legacy 'talemate_env' directory. Continuing installation.
    )
)

REM ---------[ Clean reinstall check ]---------
SET "NEED_CLEAN=0"
IF EXIST ".venv" SET "NEED_CLEAN=1"
IF EXIST "embedded_python" SET "NEED_CLEAN=1"
IF EXIST "embedded_node" SET "NEED_CLEAN=1"

IF "%NEED_CLEAN%"=="1" (
    ECHO.
    ECHO Detected existing Talemate environments.
    REM Prompt user (empty input defaults to Y)
    SET "ANSWER=Y"
    SET /P "ANSWER=Perform a clean reinstall of the python and node.js environments? [Y/n] "
    IF /I "!ANSWER!"=="N" (
        ECHO Installation aborted by user.
        GOTO :EOF
    )
    ECHO Removing previous installation...
    IF EXIST ".venv" RD /S /Q ".venv"
    IF EXIST "embedded_python" RD /S /Q "embedded_python"
    IF EXIST "embedded_node" RD /S /Q "embedded_node"
    ECHO Cleanup complete.
)

REM ---------[ Version configuration ]---------
SET "PYTHON_VERSION=3.11.9"
SET "NODE_VERSION=22.16.0"

REM ---------[ Detect architecture & choose download URL ]---------
REM Prefer PROCESSOR_ARCHITEW6432 when the script is run from a 32-bit shell on 64-bit Windows
IF DEFINED PROCESSOR_ARCHITEW6432 (
    SET "ARCH=%PROCESSOR_ARCHITEW6432%"
) ELSE (
    SET "ARCH=%PROCESSOR_ARCHITECTURE%"
)

REM Map architecture to download URL
IF /I "%ARCH%"=="AMD64" (
    SET "PY_URL=https://www.python.org/ftp/python/%PYTHON_VERSION%/python-%PYTHON_VERSION%-embed-amd64.zip"
    SET "NODE_URL=https://nodejs.org/dist/v%NODE_VERSION%/node-v%NODE_VERSION%-win-x64.zip"
) ELSE IF /I "%ARCH%"=="IA64" (
    REM Itanium systems are rare, but AMD64 build works with WoW64 layer
    SET "PY_URL=https://www.python.org/ftp/python/%PYTHON_VERSION%/python-%PYTHON_VERSION%-embed-amd64.zip"
    SET "NODE_URL=https://nodejs.org/dist/v%NODE_VERSION%/node-v%NODE_VERSION%-win-x64.zip"
) ELSE IF /I "%ARCH%"=="ARM64" (
    SET "PY_URL=https://www.python.org/ftp/python/%PYTHON_VERSION%/python-%PYTHON_VERSION%-embed-arm64.zip"
    SET "NODE_URL=https://nodejs.org/dist/v%NODE_VERSION%/node-v%NODE_VERSION%-win-arm64.zip"
) ELSE (
    REM Fallback to 64-bit build for x86 / unknown architectures
    SET "PY_URL=https://www.python.org/ftp/python/%PYTHON_VERSION%/python-%PYTHON_VERSION%-embed-amd64.zip"
    SET "NODE_URL=https://nodejs.org/dist/v%NODE_VERSION%/node-v%NODE_VERSION%-win-x86.zip"
)
ECHO Detected architecture: %ARCH%
ECHO Downloading embedded Python from: %PY_URL%

REM ---------[ Download ]---------
SET "PY_ZIP=python_embed.zip"

where curl >nul 2>&1
IF %ERRORLEVEL% EQU 0 (
    ECHO Using curl to download Python...
    curl -L -# -o "%PY_ZIP%" "%PY_URL%" || CALL :die "Failed to download Python embed package with curl."
) ELSE (
    ECHO curl not found, falling back to bitsadmin...
    bitsadmin /transfer "DownloadPython" /download /priority normal "%PY_URL%" "%CD%\%PY_ZIP%" || CALL :die "Failed to download Python embed package (curl & bitsadmin unavailable)."
)

REM ---------[ Extract ]---------
SET "PY_DIR=embedded_python"
IF EXIST "%PY_DIR%" RD /S /Q "%PY_DIR%"
mkdir "%PY_DIR%" || CALL :die "Could not create directory %PY_DIR%."

where tar >nul 2>&1
IF %ERRORLEVEL% EQU 0 (
    ECHO Extracting with tar...
    tar -xf "%PY_ZIP%" -C "%PY_DIR%"
    REM tar may return non-zero on exFAT due to timestamp warnings; verify extraction by checking for python.exe
    IF NOT EXIST "%PY_DIR%\python.exe" CALL :die "Failed to extract Python embed package with tar."
) ELSE (
    CALL :die "tar utility not found (required to unpack zip without PowerShell)."
)

DEL /F /Q "%PY_ZIP%"

SET "PYTHON=%PY_DIR%\python.exe"
ECHO Using embedded Python at %PYTHON%

REM ---------[ Enable site-packages in embedded Python ]---------
FOR %%f IN ("%PY_DIR%\python*._pth") DO (
    ECHO Adding 'import site' to %%~nxf ...
    echo import site>>"%%~ff"
)

REM ---------[ Ensure pip ]---------
ECHO Installing pip...
"%PYTHON%" install-utils\get-pip.py || (
    CALL :die "pip installation failed."
)

REM Upgrade pip to latest
"%PYTHON%" -m pip install --no-warn-script-location --upgrade pip || CALL :die "Failed to upgrade pip in embedded Python."

REM ---------[ Install uv ]---------
ECHO Installing uv...
"%PYTHON%" -m pip install uv || (
    CALL :die "uv installation failed."
)

REM ---------[ Create virtual environment with uv ]---------
ECHO Creating virtual environment with uv...
"%PYTHON%" -m uv venv || (
    CALL :die "Virtual environment creation failed."
)

REM ---------[ Install dependencies using embedded Python's uv ]---------
ECHO Installing backend dependencies with uv...
"%PYTHON%" -m uv sync || CALL :die "Failed to install backend dependencies with uv."

REM Activate the venv for the remainder of the script
CALL .venv\Scripts\activate

REM echo python version
python --version

REM ---------[ Config file ]---------
IF NOT EXIST config.yaml COPY config.example.yaml config.yaml

REM ---------[ Node.js portable runtime ]---------
ECHO.
ECHO Downloading portable Node.js runtime...

REM Node download variables already set earlier based on %ARCH%.
ECHO Downloading Node.js from: %NODE_URL%

SET "NODE_ZIP=node_embed.zip"

where curl >nul 2>&1
IF %ERRORLEVEL% EQU 0 (
    ECHO Using curl to download Node.js...
    curl -L -# -o "%NODE_ZIP%" "%NODE_URL%" || CALL :die "Failed to download Node.js package with curl."
) ELSE (
    ECHO curl not found, falling back to bitsadmin...
    bitsadmin /transfer "DownloadNode" /download /priority normal "%NODE_URL%" "%CD%\%NODE_ZIP%" || CALL :die "Failed to download Node.js package (curl & bitsadmin unavailable)."
)

REM ---------[ Extract Node.js ]---------
SET "NODE_DIR=embedded_node"
IF EXIST "%NODE_DIR%" RD /S /Q "%NODE_DIR%"
mkdir "%NODE_DIR%" || CALL :die "Could not create directory %NODE_DIR%."

where tar >nul 2>&1
IF %ERRORLEVEL% EQU 0 (
    ECHO Extracting Node.js...
    tar -xf "%NODE_ZIP%" -C "%NODE_DIR%" --strip-components 1
    REM tar may return non-zero on exFAT due to timestamp warnings; verify extraction by checking for node.exe
    IF NOT EXIST "%NODE_DIR%\node.exe" CALL :die "Failed to extract Node.js package with tar."
) ELSE (
    CALL :die "tar utility not found (required to unpack zip without PowerShell)."
)

DEL /F /Q "%NODE_ZIP%"

REM Prepend Node.js folder to PATH so npm & node are available
SET "PATH=%CD%\%NODE_DIR%;%PATH%"
ECHO Using portable Node.js at %CD%\%NODE_DIR%\node.exe
ECHO Node.js version:
node -v

REM ---------[ Frontend ]---------
ECHO Installing frontend dependencies...
CD talemate_frontend
CALL npm install || CALL :die "npm install failed."

ECHO Building frontend...
CALL npm run build || CALL :die "Frontend build failed."

REM Return to repo root
CD ..

REM ---------[ FFmpeg installation (optional) ]---------
ECHO.
ECHO Attempting to install FFmpeg...
IF EXIST "install-ffmpeg.bat" (
    CALL install-ffmpeg.bat
    IF %ERRORLEVEL% NEQ 0 (
        ECHO.
        ECHO [WARNING] FFmpeg installation failed or was skipped.
        ECHO Some TTS features may not work without FFmpeg.
        ECHO You can run install-ffmpeg.bat manually later to install it.
        ECHO.
    )
) ELSE (
    ECHO [WARNING] install-ffmpeg.bat not found. Skipping FFmpeg installation.
)

ECHO.
ECHO ==============================
ECHO  Installation completed!
ECHO ==============================
PAUSE

ENDLOCAL
