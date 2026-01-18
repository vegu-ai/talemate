# Stage 1: Frontend build
FROM node:21-slim AS frontend-build

WORKDIR /app

# Copy frontend package files
COPY talemate_frontend/package*.json ./

# Install dependencies
RUN npm ci

# Copy frontend source
COPY talemate_frontend/ ./

# Build frontend
RUN npm run build

# Stage 2: Backend build
FROM python:3.11-slim AS backend-build

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    bash \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install uv

# Copy installation files
COPY pyproject.toml uv.lock /app/

# Copy the Python source code (needed for editable install)
COPY ./src /app/src

# Create virtual environment and install dependencies (includes CUDA support via pyproject.toml)
RUN uv sync

# Stage 3: Final image
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    bash \
    wget \
    tar \
    xz-utils \
    gettext-base \
    && rm -rf /var/lib/apt/lists/*

# Install uv in the final stage
RUN pip install uv

# Copy virtual environment from backend-build stage
COPY --from=backend-build /app/.venv /app/.venv

# Download and install FFmpeg 8.0 with shared libraries into .venv (matching Windows installer approach)
# Using BtbN FFmpeg builds which provide shared libraries - verified to work
# Note: We tried using jrottenberg/ffmpeg:8.0-ubuntu image but copying libraries from it didn't work properly,
#       so we use the direct download approach which is more reliable and matches the Windows installer
RUN cd /tmp && \
    wget -q https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl-shared.tar.xz -O ffmpeg.tar.xz && \
    tar -xf ffmpeg.tar.xz && \
    cp -a ffmpeg-master-latest-linux64-gpl-shared/bin/* /app/.venv/bin/ && \
    cp -a ffmpeg-master-latest-linux64-gpl-shared/lib/* /app/.venv/lib/ && \
    rm -rf ffmpeg-master-latest-linux64-gpl-shared ffmpeg.tar.xz && \
    LD_LIBRARY_PATH=/app/.venv/lib /app/.venv/bin/ffmpeg -version | head -n 1

# Set LD_LIBRARY_PATH so torchcodec can find ffmpeg libraries at runtime
ENV LD_LIBRARY_PATH=/app/.venv/lib:${LD_LIBRARY_PATH}

# Copy Python source code
COPY --from=backend-build /app/src /app/src

# Copy Node.js build artifacts from frontend-build stage
COPY --from=frontend-build /app/dist /app/talemate_frontend/dist

# Preserve index.html as template for runtime envsubst substitution
COPY --from=frontend-build /app/dist/index.html /app/talemate_frontend/dist/index.template.html

# Copy the frontend WSGI file if it exists
COPY frontend_wsgi.py /app/frontend_wsgi.py

# Copy base config
COPY config.example.yaml /app/config.yaml

# Copy essentials
COPY scenes/ /app/scenes/
COPY templates/ /app/templates/
COPY chroma* /app/
COPY tts/ /app/tts/

# Copy entrypoint script for runtime environment variable substitution
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

# Set PYTHONPATH to include the src directory
ENV PYTHONPATH=/app/src:$PYTHONPATH

# Make ports available to the world outside this container
EXPOSE 5050
EXPOSE 8080

# Use entrypoint for runtime config, CMD for the actual server
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uv", "run", "src/talemate/server/run.py", "runserver", "--host", "0.0.0.0", "--port", "5050", "--frontend-host", "0.0.0.0", "--frontend-port", "8080"]
