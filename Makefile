.PHONY: setup check fmt build

setup: ## install Python and player dependencies
	uv sync
	cd player && npm ci

check: ## lint, type-check and test everything
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy
	uv run pytest
	cd player && npm run typecheck && npm test

fmt: ## format and auto-fix Python code
	uv run ruff format .
	uv run ruff check --fix .

build: ## bundle the player and copy it into the Python package
	cd player && npm run build
	mkdir -p src/runreel/_player && cp player/dist/player.js src/runreel/_player/player.js
