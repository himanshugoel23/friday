# syntax=docker/dockerfile:1.7
# Friday: one image, many roles (`friday serve`, `friday worker --roles ...`, migrations).
# Stage 1 builds a self-contained virtualenv with uv; stage 2 copies only that venv.

ARG PYTHON_IMAGE=python:3.12-slim-bookworm

FROM ${PYTHON_IMAGE} AS builder
COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /uvx /usr/local/bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src
# 1) dependencies only (cached until pyproject/uv.lock change)
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
# 2) the project itself, installed (not editable) into the venv
COPY friday ./friday
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

FROM ${PYTHON_IMAGE} AS runtime
ARG GIT_SHA=unknown
LABEL org.opencontainers.image.title="friday" \
      org.opencontainers.image.revision="${GIT_SHA}"
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FRIDAY_HOST=0.0.0.0 \
    FRIDAY_PORT=8000 \
    FRIDAY_LOG_JSON=true \
    FRIDAY_MEDIA_DIR=/var/lib/friday/media \
    FRIDAY_PAUSE_FILE=/var/lib/friday/PAUSED
# non-root user; /var/lib/friday holds the kill-switch flag (shared volume in compose)
RUN groupadd --system --gid 10001 friday \
 && useradd --system --uid 10001 --gid friday --home-dir /home/friday --create-home --shell /usr/sbin/nologin friday \
 && mkdir -p /var/lib/friday/media \
 && chown -R friday:friday /var/lib/friday
COPY --from=builder /opt/venv /opt/venv
WORKDIR /home/friday
USER friday
EXPOSE 8000
ENTRYPOINT ["friday"]
CMD ["serve"]
