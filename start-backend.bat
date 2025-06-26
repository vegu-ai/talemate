@echo off
set TALEMATE_DEBUG=1

REM Ensure venv exists and activate it
IF NOT EXIST ".venv\Scripts\activate.bat" (
    echo [ERROR] .venv virtual environment not found. Please run install.bat first.
    goto :eof
)
call .venv\Scripts\activate

REM Use embedded Python's uv to run with proper dependency resolution
embedded_python\python.exe -m uv run src\talemate\server\run.py runserver --host 0.0.0.0 --port 5050 --backend-only

goto :eof

:error
echo Failed to create virtual environment. Aborting.
exit /b 1