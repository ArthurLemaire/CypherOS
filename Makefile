.DEFAULT_GOAL := help
.PHONY: help install lint fmt type test cov clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## Install package with dev extras
	pip install -e ".[dev,vector]"
	pre-commit install

lint: ## Run ruff
	ruff check src tests

fmt: ## Auto-format
	ruff format src tests
	ruff check --fix src tests

type: ## Run mypy --strict
	mypy src/dots

test: ## Run the test suite
	pytest

cov: ## Run tests with coverage report
	pytest --cov=dots --cov-report=html

clean: ## Remove caches and build artifacts
	rm -rf build dist *.egg-info .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} +
