#!/bin/bash

# use the portable Node.js provisioned by install.sh (falls back to system Node)
source install-utils/node-env.sh
activate_embedded_node

cd talemate_frontend
export COREPACK_ENABLE_DOWNLOAD_PROMPT=0
corepack pnpm run serve --host 0.0.0.0 --port "${TALEMATE_FRONTEND_PORT:-8082}"