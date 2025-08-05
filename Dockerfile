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
    && rm -rf /var/lib/apt/lists/*

# Install uv in the final stage
RUN pip install uv

# Copy virtual environment from backend-build stage
COPY --from=backend-build /app/.venv /app/.venv

# Copy Python source code
COPY --from=backend-build /app/src /app/src

# Copy Node.js build artifacts from frontend-build stage
COPY --from=frontend-build /app/dist /app/talemate_frontend/dist

# Copy the frontend WSGI file if it exists
COPY frontend_wsgi.py /app/frontend_wsgi.py

# Copy base config
COPY config.example.yaml /app/config.yaml

# Copy essentials
COPY scenes templates chroma* /app/

# Set PYTHONPATH to include the src directory
ENV PYTHONPATH=/app/src:$PYTHONPATH

# Make ports available to the world outside this container
EXPOSE 5050
EXPOSE 8080

# Use bash as the shell, activate the virtual environment, and run backend server
CMD ["uv", "run", "src/talemate/server/run.py", "runserver", "--host", "0.0.0.0", "--port", "5050", "--frontend-host", "0.0.0.0", "--frontend-port", "8080"]