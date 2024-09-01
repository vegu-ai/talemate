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

# Install poetry
RUN pip install poetry

# Copy poetry files
COPY pyproject.toml poetry.lock* /app/

# Create a virtual environment
RUN python -m venv /app/talemate_env

# Activate virtual environment and install dependencies
RUN . /app/talemate_env/bin/activate && \
    poetry config virtualenvs.create false && \
    poetry install --no-dev --no-root

# Copy the Python source code
COPY ./src /app/src

# Stage 3: Final image
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    bash \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from backend-build stage
COPY --from=backend-build /app/talemate_env /app/talemate_env

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
CMD ["poetry run src/talemate/server/run.py runserver --host 0.0.0.0 --port 5050 --frontend-host 0.0.0.0 --frontend-port 8080"]