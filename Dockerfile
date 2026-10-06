# syntax=docker/dockerfile:1

# Layers are ordered from least to most frequently changed:
#   model - embedding model, rebuilt only when EMBEDDING_MODEL changes
#   deps  - Python dependencies, rebuilt only when pyproject.toml / uv.lock change
#   final - application code, rebuilt when src/ changes

# ------------------------------------------------------------
# Base
# ------------------------------------------------------------

FROM python:3.12-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/huggingface


# ------------------------------------------------------------
# Embedding model (llm/embeddings.py) — keep EMBEDDING_MODEL equal to config/settings.py's
# ------------------------------------------------------------

FROM base AS model

ARG EMBEDDING_MODEL=BAAI/bge-base-en-v1.5

# Make the build argument available to the Python process
ENV EMBEDDING_MODEL=${EMBEDDING_MODEL}

# Only the files the model needs: the duplicate pytorch_model.bin and onnx/ weights are skipped.
RUN pip install --no-cache-dir "huggingface_hub>=0.25,<1" \
    && python -c "\
import os; \
from huggingface_hub import snapshot_download; \
snapshot_download( \
    os.environ['EMBEDDING_MODEL'], \
    allow_patterns=[ \
        '*.json', \
        '*.txt', \
        'model.safetensors', \
        '1_Pooling/*' \
    ] \
)"


# ------------------------------------------------------------
# Python dependencies
# ------------------------------------------------------------

FROM base AS deps

# Pin uv version for reproducible builds
COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /bin/uv

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Copy only dependency files first so this layer stays cached
# when application source code changes. On Linux, uv.lock resolves torch to the CPU-only
# build (download.pytorch.org), so no NVIDIA libraries are installed.
COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project


# ------------------------------------------------------------
# Final application image
# ------------------------------------------------------------

FROM base AS final

WORKDIR /app

# Create non-root application user
RUN useradd \
        --create-home \
        --uid 1000 \
        --shell /usr/sbin/nologin \
        radar

# Copy the pre-downloaded embedding model
COPY --from=model /opt/huggingface /opt/huggingface

# Copy the pre-built Python virtual environment
COPY --from=deps /app/.venv /app/.venv

# Application source
COPY src/ ./src/

# Runtime configuration. The model is baked in, so never reach out to Hugging Face at runtime
# (no downloads, no update checks, no usage statistics).
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src" \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1

# Run as non-root
USER radar

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "src"]
