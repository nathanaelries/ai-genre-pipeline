# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Stage 1: builder — install Python deps into an isolated venv.
# Keeping the build tooling out of the final image keeps it small.
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# build-essential is only needed to compile a few wheels; it stays in builder.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create a self-contained virtualenv we can copy wholesale into the runtime.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 2: runtime — slim image with ffmpeg + the prebuilt venv.
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

# ffmpeg is a hard runtime dependency for the assembly stage.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy the ready-made virtualenv from the builder stage.
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Run as a non-root user; outputs/ is a mounted volume owned by this user.
RUN useradd --create-home --uid 1000 appuser
WORKDIR /app

COPY --chown=appuser:appuser app/ ./app/
COPY --chown=appuser:appuser pyproject.toml ./

USER appuser

# Default: show CLI help. `docker compose run orchestrator run` to execute.
ENTRYPOINT ["python", "-m", "app.main"]
CMD ["--help"]
