@echo off
SET "PATH=%~dp0embedded_node;%PATH%"
if "%TALEMATE_FRONTEND_PORT%"=="" set TALEMATE_FRONTEND_PORT=8082
start cmd /k node "%~dp0install-utils\pnpm.cjs" run serve --host 0.0.0.0 --port %TALEMATE_FRONTEND_PORT%
