.PHONY: help install lint format typecheck test cov check build clean

help:
	@echo "install    install the package plus dev and test extras"
	@echo "lint       ruff check and format check (what CI runs)"
	@echo "format     rewrite files with ruff format"
	@echo "typecheck  mypy"
	@echo "test       pytest"
	@echo "cov        pytest with coverage and the floor enforced"
	@echo "check      everything CI runs, in the same order"
	@echo "build      build the wheel and sdist, then twine check"
	@echo "clean      remove build artifacts and caches"

install:
	pip install -e ".[dev,test]"

lint:
	ruff check supervisor/ tests/
	ruff format --check supervisor/ tests/

format:
	ruff format supervisor/ tests/
	ruff check --fix supervisor/ tests/

typecheck:
	mypy supervisor/ --ignore-missing-imports

test:
	pytest tests/ -q

cov:
	pytest tests/ -q --cov --cov-report=term-missing

check: lint typecheck cov

build:
	rm -rf dist build
	python -m build
	twine check dist/*

clean:
	rm -rf dist build .coverage htmlcov
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache .mypy_cache
