# syntax=docker/dockerfile:1
# Layers ordered from least to most often changed, so a rebuild only redoes what changed:
#   model  - the embedding model, downloaded once; rebuilt only when EMBEDDING_MODEL changes
#   deps   - Python dependencies; rebuilt only when pyproject.toml / uv.lock change
#   final  - the app code; the only layer an ordinary code change rebuilds

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/huggingface


# The local embedding model (llm/embeddings.py). Independent of the lockfile, so a dependency
# bump never re-downloads it. Keep EMBEDDING_MODEL equal to config/settings.py's.
FROM base AS model
ARG EMBEDDING_MODEL=BAAI/bge-base-en-v1.5
RUN pip install --no-cache-dir "huggingface_hub>=0.25,<1" \
 && python -c "import os; from huggingface_hub import snapshot_download; snapshot_download(os.environ['EMBEDDING_MODEL'], allow_patterns=['*.json', '*.txt', 'model.safetensors', '1_Pooling/*'])"


FROM base AS deps
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project


FROM base
WORKDIR /app
RUN useradd --create-home --uid 1000 radar
COPY --from=model /opt/huggingface /opt/huggingface
COPY --from=deps /app/.venv /app/.venv
COPY src/ ./src/
# The model is baked in, so never reach out to Hugging Face at runtime.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/src \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1
USER radar
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "src"]
