@echo off
set TALEMATE_DEBUG=1
start cmd /k "uv run src\talemate\server\run.py runserver --host 0.0.0.0 --port 5050 --backend-only"