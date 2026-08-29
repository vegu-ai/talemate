# The backend-build stage creates the virtual environment and the final stage
# runs it, so both must install the same uv.
ARG UV_VERSION=0.12.5

# Stage 1: Frontend build
FROM node:22-slim AS frontend-build

WORKDIR /app

# Enable pnpm via corepack (version pinned by package.json "packageManager").
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
# pnpm asks before it purges a modules directory, and aborts when no TTY can
# answer. https://pnpm.io/settings#confirmmodulespurge
ENV CI=true
ARG COREPACK_VERSION=0.35.0
RUN npm install -g corepack@${COREPACK_VERSION} && corepack enable

# Copy frontend manifest, lockfile and pnpm settings
COPY talemate_frontend/package.json talemate_frontend/pnpm-lock.yaml talemate_frontend/pnpm-workspace.yaml ./

# Install dependencies
RUN pnpm install --frozen-lockfile

# Copy frontend source
COPY talemate_frontend/ ./

# Build frontend
RUN pnpm build

# Stage 2: Backend build
FROM python:3.11-slim AS backend-build

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    bash \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install uv
ARG UV_VERSION
RUN pip install uv==${UV_VERSION}

# Copy installation files
COPY pyproject.toml uv.lock /app/

# Copy the Python source code (needed for editable install)
COPY ./src /app/src

# Create virtual environment and install dependencies (includes CUDA support via pyproject.toml)
RUN uv sync

# The help agent reads the bundled documentation from TALEMATE_ROOT/docs, and it
# reads nothing but markdown. Dropping the rest here keeps 36 MB of screenshots
# out of the final image instead of deleting them in a layer that still ships.
COPY docs /app/docs
RUN find /app/docs -type f ! -name "*.md" -delete && \
    find /app/docs -depth -type d -empty -delete

# Stage 3: Final image
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    bash \
    wget \
    tar \
    xz-utils \
    gettext-base \
    libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

# Install uv in the final stage
ARG UV_VERSION
RUN pip install uv==${UV_VERSION}

# Node.js runtime for the pi coding agent (Pi Bridge client), reused from the
# frontend build stage so the final image needs no extra apt source
COPY --from=frontend-build /usr/local/bin/node /usr/local/bin/node
COPY --from=frontend-build /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -sf /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && \
    ln -sf /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

# Install pi for the Pi Bridge client (override the version via build arg)
ARG PI_VERSION=0.80.10
RUN npm install -g @earendil-works/pi-coding-agent@${PI_VERSION} && \
    npm cache clean --force && \
    pi --version

# pi config dir (models.json, auth.json) - mounted as a volume in docker-compose
# so it is host-editable and survives container recreation
ENV PI_CODING_AGENT_DIR=/app/pi
RUN mkdir -p /app/pi

# Copy virtual environment from backend-build stage
COPY --from=backend-build /app/.venv /app/.venv

# FFmpeg shared libraries for torchcodec, which loads FFmpeg 4 to 8 only.
# The BtbN master asset now ships FFmpeg 9, so this tracks the 8.1 release branch.
ARG FFMPEG_BUILD=ffmpeg-n8.1-latest-linux64-gpl-shared-8.1
RUN cd /tmp && \
    wget -q https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/${FFMPEG_BUILD}.tar.xz -O ffmpeg.tar.xz && \
    tar -xf ffmpeg.tar.xz && \
    cp -a ${FFMPEG_BUILD}/bin/* /app/.venv/bin/ && \
    cp -a ${FFMPEG_BUILD}/lib/* /app/.venv/lib/ && \
    rm -rf ${FFMPEG_BUILD} ffmpeg.tar.xz && \
    LD_LIBRARY_PATH=/app/.venv/lib /app/.venv/bin/ffmpeg -version | head -n 1

# Set LD_LIBRARY_PATH so torchcodec can find ffmpeg libraries at runtime
ENV LD_LIBRARY_PATH=/app/.venv/lib:${LD_LIBRARY_PATH}

# Fail the build, instead of scene loading at runtime, when the two no longer match.
RUN /app/.venv/bin/python -B -c "import torchcodec.decoders"

# Copy Python source code
COPY --from=backend-build /app/src /app/src

COPY --from=backend-build /app/docs /app/docs

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

# Bind on all interfaces inside the container by default. Ports can be
# overridden with TALEMATE_BACKEND_PORT / TALEMATE_FRONTEND_PORT.
ENV TALEMATE_BACKEND_HOST=0.0.0.0
ENV TALEMATE_FRONTEND_HOST=0.0.0.0

# Make ports available to the world outside this container
EXPOSE 5050
EXPOSE 8082

# Use entrypoint for runtime config, CMD for the actual server
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uv", "run", "src/talemate/server/run.py", "runserver"]
