# The upstream assistant at one pinned commit, plus the rail_k8s wrapper. Upstream is not modified.
# Build: scripts/build-image.sh   Test only: docker build --target test -f image/Dockerfile .

# --- fetch upstream at the pinned commit (a commit archive never changes) ---------------------
FROM alpine:3.21 AS src
ARG UPSTREAM_COMMIT=c7c371f898d6e9d06d70d8c4c69d579dad447342
ADD https://github.com/cardohso/rail-regulation-rag/archive/${UPSTREAM_COMMIT}.tar.gz /tmp/upstream.tar.gz
RUN mkdir /upstream && tar -xzf /tmp/upstream.tar.gz -C /upstream --strip-components=1

# --- runtime ----------------------------------------------------------------------------------
FROM python:3.12-slim AS base
ARG UPSTREAM_COMMIT=c7c371f898d6e9d06d70d8c4c69d579dad447342
LABEL org.opencontainers.image.source="https://github.com/cardohso/rail-rag-k8s" \
      org.opencontainers.image.licenses="MIT" \
      io.github.cardohso.upstream-commit="${UPSTREAM_COMMIT}"

COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    HF_HOME=/home/app/.cache/huggingface \
    FASTEMBED_CACHE_PATH=/home/app/.cache/fastembed \
    HF_HUB_DISABLE_TELEMETRY=1 \
    PATH=/home/app/rail-rag/.venv/bin:$PATH

RUN useradd --create-home --uid 1000 app
USER app
WORKDIR /home/app/rail-rag

# Dependencies first, from upstream's lock file, so code changes do not reinstall them.
COPY --from=src --chown=app /upstream/pyproject.toml /upstream/uv.lock /upstream/README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY --from=src --chown=app /upstream/src ./src
COPY --from=src --chown=app /upstream/data/sources.yaml ./data/sources.yaml
COPY --from=src --chown=app /upstream/data/processed ./data/processed
RUN uv sync --frozen --no-dev

# Both models are downloaded now, so the pod needs no network for retrieval and can run with a
# read-only root filesystem.
RUN python -c "from rail_rag.embeddings import LocalEmbedder, BM25Encoder; \
LocalEmbedder().embed_query('probe'); BM25Encoder().embed_query('probe')"
ENV HF_HUB_OFFLINE=1

COPY --chown=app wrapper /home/app/wrapper
RUN uv pip install --python .venv/bin/python /home/app/wrapper

EXPOSE 7860
CMD ["uvicorn", "rail_k8s.app:app", "--host", "0.0.0.0", "--port", "7860", \
     "--no-access-log", "--timeout-graceful-shutdown", "25"]

# --- tests, run inside the image so they use the same dependencies ----------------------------
FROM base AS test
RUN uv pip install --python .venv/bin/python pytest==9.1.1
WORKDIR /home/app/wrapper
RUN python -m pytest

# --- the image that ships ---------------------------------------------------------------------
FROM base AS final
