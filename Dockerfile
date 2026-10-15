# Build from qozon_multi_agent; .dockerignore allows only code, lockfiles and public registry.
FROM python:3.12.14-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.12.9 /uv /uvx /bin/
WORKDIR /app
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --locked --no-default-groups --no-editable && uv cache clean
COPY release/publication.json ./release/publication.json
ENV PATH="/app/.venv/bin:$PATH" QOZON_RAG_PUBLICATION_MANIFEST=/app/release/publication.json
# Cloudflare admission uses an internal secret, not visitor forwarding headers.
# Other hosts must configure their trusted proxy addresses explicitly.
CMD ["sh", "-c", "exec uvicorn qozon_multi_agent.api.app:app --host 0.0.0.0 --port \"${PORT:-8000}\" --workers 1 --limit-concurrency 16 --no-access-log --proxy-headers"]
