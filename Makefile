.PHONY: fmt lint typecheck test check destroy

fmt:
	uv run ruff format .
	uv run ruff check --fix .

lint:
	uv run ruff format --check .
	uv run ruff check .

typecheck:
	uv run mypy

test:
	uv run pytest

check: lint typecheck test

# Tears clickops down in the safe order. Prompts for confirmation; DRY_RUN=1 only prints the plan.
destroy:
	./scripts/destroy.sh
