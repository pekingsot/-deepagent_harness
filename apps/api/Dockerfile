FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/app/.venv PATH="/app/.venv/bin:$PATH" HARNESS_HOST=0.0.0.0
COPY pyproject.toml README.md ./
COPY src ./src
RUN uv sync --no-dev --no-cache
EXPOSE 8000
CMD ["harness-api"]

