# syntax=docker/dockerfile:1
# =============================================================================
# Dragonfly Civil - Production Dockerfile
# =============================================================================
#
# Multi-stage build optimized for Python/FastAPI deployment on Railway.
#
# DESIGN GOALS:
# 1. DETERMINISTIC: No cached buildpacks - explicit dependency installation
# 2. TRACEABLE: Git SHA baked into the image as RAILWAY_GIT_COMMIT_SHA
# 3. MINIMAL: Runtime image has no build tools (gcc, dev headers)
# 4. FLEXIBLE: Same image for API and Workers (CMD override)
#
# BUILD:
#   docker build --build-arg GIT_SHA=$(git rev-parse HEAD) -t dragonfly:latest .
#
# RUN (API):
#   docker run -p 8000:8000 dragonfly:latest
#
# RUN (Worker):
#   docker run dragonfly:latest python -m workers.runner
#
# =============================================================================

# -----------------------------------------------------------------------------
# STAGE 1: Builder
# -----------------------------------------------------------------------------
# Install build dependencies and compile Python packages.
# This stage is discarded - only the installed packages are copied to runtime.
# -----------------------------------------------------------------------------
FROM python:3.12-slim AS builder

# Prevent Python from writing .pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Install build dependencies for psycopg, cryptography, etc.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    libffi-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (Docker layer caching optimization)
COPY requirements.txt .

# Install Python packages to user directory (for easy copying to runtime)
RUN pip install --user --no-cache-dir -r requirements.txt


# -----------------------------------------------------------------------------
# STAGE 2: Runtime
# -----------------------------------------------------------------------------
# Minimal runtime image with only what's needed to run the application.
# No gcc, no dev headers, no build tools.
# -----------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# Prevent Python from writing .pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install runtime-only dependencies (libpq for psycopg, curl for healthcheck)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash dragonfly

# Copy installed Python packages from builder stage
COPY --from=builder /root/.local /home/dragonfly/.local

# Ensure user-installed packages are in PATH
ENV PATH="/home/dragonfly/.local/bin:$PATH" \
    PYTHONPATH="/app"

WORKDIR /app

# Copy application code
# Order: least-changing first for better layer caching
COPY config ./config
COPY src ./src
COPY backend ./backend
COPY workers ./workers
COPY etl ./etl
COPY tools ./tools
COPY brain ./brain

# -----------------------------------------------------------------------------
# GIT SHA TRACEABILITY
# -----------------------------------------------------------------------------
# The GIT_SHA build arg is baked into the image as RAILWAY_GIT_COMMIT_SHA.
# This ensures every container knows exactly which commit built it.
#
# Build with: docker build --build-arg GIT_SHA=$(git rev-parse HEAD) ...
# -----------------------------------------------------------------------------
ARG GIT_SHA=unknown
ENV RAILWAY_GIT_COMMIT_SHA=${GIT_SHA}

# Add build metadata as labels
LABEL org.opencontainers.image.revision="${GIT_SHA}" \
    org.opencontainers.image.title="Dragonfly Civil" \
    org.opencontainers.image.description="Judgment Enforcement Operating System" \
    org.opencontainers.image.vendor="Dragonfly Civil"

# Switch to non-root user for security
RUN chown -R dragonfly:dragonfly /app
USER dragonfly

# Expose the FastAPI port
EXPOSE 8000

# -----------------------------------------------------------------------------
# HEALTHCHECK
# -----------------------------------------------------------------------------
# For API deployments, check the /health endpoint every 30 seconds.
# Uses PORT env var (Railway-assigned) with fallback to 8000 for local.
# Workers should override this or use --no-healthcheck.
# -----------------------------------------------------------------------------
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl --fail http://localhost:${PORT:-8000}/health || exit 1

# -----------------------------------------------------------------------------
# DEFAULT COMMAND
# -----------------------------------------------------------------------------
# Default: Run the FastAPI API server via the run_uvicorn launcher.
# This enforces strict PORT binding and provides structured startup logs.
#
# Override for workers: docker run <image> python -m workers.runner
#
# NOTE: We use python -m tools.run_uvicorn instead of raw uvicorn because:
#   1. Strict PORT enforcement in production (fail fast if missing)
#   2. Single startup log line for log aggregation
#   3. Git SHA traceability in startup output
# -----------------------------------------------------------------------------
CMD ["python", "-m", "tools.run_uvicorn"]
