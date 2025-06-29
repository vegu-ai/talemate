@echo off

REM Define fatal-error handler
REM Usage: CALL :die "Message explaining what failed"
goto :after_die

:die
echo.
echo ============================================================
echo   !!! UNABLE TO START TALEMATE !!!
echo   %*
echo ============================================================
pause
exit 1

:after_die

REM Automatically run installer if prerequisites are missing
SET "NEED_INSTALL="
IF NOT EXIST "embedded_python\python.exe" (
    SET "NEED_INSTALL=1"
)
IF NOT EXIST ".venv" (
    SET "NEED_INSTALL=1"
)
IF NOT DEFINED NEED_INSTALL (
    "embedded_python\python.exe" -m uv -h >nul 2>&1 || SET "NEED_INSTALL=1"
)

IF DEFINED NEED_INSTALL (
    ECHO One or more prerequisites not found - running install.bat...
    CALL install.bat || GOTO :die
    CLS
)

REM Set HF_HUB_DISABLE_SYMLINKS_WARNING to avoid warning about symlinks
SET "HF_HUB_DISABLE_SYMLINKS_WARNING=1"

REM Use embedded Python's uv to run with proper dependency resolution
embedded_python\python.exe -m uv run src\talemate\server\run.py runserver --host 0.0.0.0 --port 5050