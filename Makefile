install:
	uv sync --group dev

api:
	uv run harness-api

worker:
	uv run harness-worker

check:
	uv run python scripts/check_structure.py
	uv run pytest tests -q
	uv run ruff check src tests migrations scripts/check_structure.py
	uv run mypy

upgrade:
	uv lock --upgrade
	uv sync --locked
