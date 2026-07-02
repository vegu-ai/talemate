if "%TALEMATE_FRONTEND_PORT%"=="" set TALEMATE_FRONTEND_PORT=8082
set COREPACK_ENABLE_DOWNLOAD_PROMPT=0
start cmd /k "cd talemate_frontend && corepack pnpm run serve --host 0.0.0.0 --port %TALEMATE_FRONTEND_PORT%"