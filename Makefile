.PHONY: check lint test build

# Run all QA checks (use before pushing PRs)
check: lint test build

# Python lint + format check
lint:
	python -m ruff check app/ tests/
	python -m ruff format --check app/ tests/
	cd ui && npx eslint . --max-warnings 20

# Backend tests
test:
	python -m pytest tests/ -x -q --tb=short

# Frontend build verification
build:
	cd ui && npx next build

# Auto-fix Python lint issues
fix:
	python -m ruff check --fix app/ tests/
	python -m ruff format app/ tests/
