#!/bin/bash
set -e

#
# Talemate Docker Entrypoint
#
# Replaces environment variable placeholders in the frontend bundle
# at container startup, enabling runtime configuration.
#
# Environment Variables:
#   VITE_TALEMATE_BACKEND_WEBSOCKET_URL - WebSocket URL for backend connection
#                                          Leave empty/unset for auto-detection
#

TEMPLATE_FILE="/app/talemate_frontend/dist/index.template.html"
OUTPUT_FILE="/app/talemate_frontend/dist/index.html"

echo "============================================"
echo "Talemate Docker Entrypoint"
echo "============================================"

if [ -f "$TEMPLATE_FILE" ]; then
    echo "Substituting environment variables..."
    echo "  VITE_TALEMATE_BACKEND_WEBSOCKET_URL: ${VITE_TALEMATE_BACKEND_WEBSOCKET_URL:-<not set, will auto-detect>}"
    
    # Use envsubst to replace ${VAR} placeholders with actual values
    envsubst < "$TEMPLATE_FILE" > "$OUTPUT_FILE"
    
    echo "Runtime config applied to index.html"
else
    echo "Warning: Template file not found, skipping envsubst"
fi

echo "Starting Talemate..."
echo "============================================"

# Execute the main command
exec "$@"
