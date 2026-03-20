FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /workspace

RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml context.md AGENTS.md build_backend.py ./
COPY autoweave ./autoweave
COPY apps ./apps
COPY configs ./configs
COPY agents ./agents
COPY docs ./docs

RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install .

CMD ["sleep", "infinity"]
