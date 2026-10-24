install:
	uv sync --group dev

api:
	uv run harness-api

worker:
	uv run harness-worker

check:
	uv run python scripts/check_structure.py
	uv run python -m unittest discover -s tests/unit -v
	uv run ruff check .
	uv run mypy

upgrade:
	uv lock --upgrade
	uv sync --locked
