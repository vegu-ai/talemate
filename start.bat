@echo off
REM Ensure venv exists and activate it
IF NOT EXIST ".venv\Scripts\activate.bat" (
    echo [ERROR] .venv virtual environment not found. Please run install.bat first.
    goto :eof
)
call .venv\Scripts\activate

REM Use uv within the venv to run the server
uv run src\talemate\server\run.py runserver --host 0.0.0.0 --port 5050

goto :eof