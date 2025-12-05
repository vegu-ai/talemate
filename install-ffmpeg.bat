@echo off

REM ===============================
REM  FFmpeg installer for Talemate
REM ===============================
REM 1. Download ffmpeg-8.0.1-full_build-shared.zip from GitHub
REM 2. Extract the archive with tar
REM 3. Copy all binaries from bin/ to .venv\Scripts\
REM 4. Clean up temporary files
REM ---------------------------------------------------------------

SETLOCAL ENABLEDELAYEDEXPANSION

REM Define fatal-error handler
REM Usage: CALL :die "Message explaining what failed"
goto :after_die

:die
echo.
echo ============================================================
echo   !!! FFMPEG INSTALLATION FAILED !!!
echo   %*
echo ============================================================
pause
exit 1

:after_die

REM ---------[ Check Prerequisites ]---------
ECHO Checking prerequisites...

REM Check for .venv directory
IF NOT EXIST ".venv\Scripts" (
    CALL :die "Virtual environment not found. Please run install.bat first to create .venv"
)

REM Check for download tools
where curl >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    where bitsadmin >nul 2>&1 || CALL :die "Neither curl nor bitsadmin found. Cannot download files."
)

REM Check for tar (built-in on Windows 10 1803+)
where tar >nul 2>&1 || CALL :die "tar command not found. Please ensure Windows 10 version 1803+ or install tar manually."

REM ---------[ Configuration ]---------
SET "FFMPEG_URL=https://github.com/GyanD/codexffmpeg/releases/download/8.0.1/ffmpeg-8.0.1-full_build-shared.zip"
SET "FFMPEG_ARCHIVE=ffmpeg-8.0.1-full_build-shared.zip"
SET "FFMPEG_TEMP_DIR=ffmpeg_temp"
SET "TARGET_DIR=.venv\Scripts"

REM ---------[ Download FFmpeg ]---------
ECHO.
ECHO Downloading FFmpeg from: %FFMPEG_URL%
ECHO This may take a few minutes...

where curl >nul 2>&1
IF %ERRORLEVEL% EQU 0 (
    ECHO Using curl to download FFmpeg...
    curl -L -# -o "%FFMPEG_ARCHIVE%" "%FFMPEG_URL%" || CALL :die "Failed to download FFmpeg archive with curl."
) ELSE (
    ECHO curl not found, falling back to bitsadmin...
    bitsadmin /transfer "DownloadFFmpeg" /download /priority normal "%FFMPEG_URL%" "%CD%\%FFMPEG_ARCHIVE%" || CALL :die "Failed to download FFmpeg archive with bitsadmin."
)

REM ---------[ Extract FFmpeg ]---------
ECHO.
ECHO Extracting FFmpeg archive...

IF EXIST "%FFMPEG_TEMP_DIR%" RD /S /Q "%FFMPEG_TEMP_DIR%"
mkdir "%FFMPEG_TEMP_DIR%" || CALL :die "Could not create temporary directory %FFMPEG_TEMP_DIR%."

ECHO Using tar to extract...
tar -xf "%FFMPEG_ARCHIVE%" -C "%FFMPEG_TEMP_DIR%" || CALL :die "Failed to extract FFmpeg archive with tar."

REM ---------[ Find bin directory ]---------
ECHO.
ECHO Locating FFmpeg binaries...

REM The archive extracts to ffmpeg-<version>-full_build-shared\bin
SET "BIN_DIR="
FOR /D %%d IN ("%FFMPEG_TEMP_DIR%\ffmpeg-*") DO (
    IF EXIST "%%d\bin" (
        SET "BIN_DIR=%%d\bin"
        ECHO Found bin directory: %%d\bin
        GOTO :found_bin
    )
)

:found_bin
IF NOT DEFINED BIN_DIR (
    CALL :die "Could not locate bin directory in extracted FFmpeg archive."
)

REM ---------[ Copy binaries to .venv\Scripts ]---------
ECHO.
ECHO Copying FFmpeg binaries to %TARGET_DIR%...

xcopy /Y /I "%BIN_DIR%\*" "%TARGET_DIR%\" >nul || CALL :die "Failed to copy FFmpeg binaries to %TARGET_DIR%."

REM ---------[ Cleanup ]---------
ECHO.
ECHO Cleaning up temporary files...

DEL /F /Q "%FFMPEG_ARCHIVE%" >nul 2>&1
IF EXIST "%FFMPEG_TEMP_DIR%" RD /S /Q "%FFMPEG_TEMP_DIR%" >nul 2>&1

REM ---------[ Verify installation ]---------
ECHO.
ECHO Verifying FFmpeg installation...

CALL .venv\Scripts\activate
ffmpeg -version >nul 2>&1
IF %ERRORLEVEL% EQU 0 (
    ECHO.
    ECHO ==============================
    ECHO  FFmpeg installation completed successfully!
    ECHO ==============================
    ffmpeg -version | findstr /C:"ffmpeg version"
) ELSE (
    ECHO [WARNING] FFmpeg installation completed but verification failed.
    ECHO You may need to restart your terminal or check your PATH.
)

ECHO.
PAUSE

ENDLOCAL
