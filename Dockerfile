# Stage 1: Frontend build
FROM node:21 AS frontend-build

ENV NODE_ENV=development

WORKDIR /app

# Copy the frontend directory contents into the container at /app
COPY ./talemate_frontend /app

# Install all dependencies and build
RUN npm install && npm run build

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

# Copy project files first
COPY pyproject.toml /app/
COPY uv.lock /app/
COPY ./src /app/src

# Create virtual environment and install dependencies
RUN uv sync --frozen --no-install-project

# Conditional PyTorch+CUDA install
ARG CUDA_AVAILABLE=false
RUN if [ "$CUDA_AVAILABLE" = "true" ]; then \
        echo "Installing PyTorch with CUDA support..." && \
        uv sync --frozen --extra cuda121; \
    else \
        echo "Installing PyTorch with CPU support..." && \
        uv sync --frozen --extra cpu; \
    fi

# Install the project itself
RUN uv pip install -e .

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

# Copy essential directories and files
COPY config.example.yaml /app/config.yaml
COPY scenes /app/scenes/
COPY templates /app/templates/

# Create chroma directory (for vector database)
RUN mkdir -p /app/chroma

# Set PYTHONPATH to include the src directory
ENV PYTHONPATH=/app/src:$PYTHONPATH

# Make ports available to the world outside this container
EXPOSE 5050
EXPOSE 8080

# Use bash as the shell, activate the virtual environment, and run backend server
CMD ["uv", "run", "src/talemate/server/run.py", "runserver", "--host", "0.0.0.0", "--port", "5050", "--frontend-host", "0.0.0.0", "--frontend-port", "8080"]
