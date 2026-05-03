PYTHON := poetry run

.PHONY: install lint typecheck test coverage verify clean run

install:
	poetry install --with dev

lint:
	$(PYTHON) ruff check .

typecheck:
	$(PYTHON) mypy app tests scripts

test:
	$(PYTHON) pytest tests/

coverage:
	$(PYTHON) pytest --cov=app --cov-report=term-missing --cov-fail-under=75

verify: lint typecheck coverage

clean:
	$(PYTHON) python -c "import pathlib, shutil; root=pathlib.Path('.'); [shutil.rmtree(p, ignore_errors=True) for p in root.rglob('__pycache__')]; [shutil.rmtree(root / name, ignore_errors=True) for name in ['.pytest_cache','.mypy_cache','.ruff_cache','htmlcov']]; [p.unlink(missing_ok=True) for pattern in ('*.pyc','*.pyo') for p in root.rglob(pattern)]; (root / '.coverage').unlink(missing_ok=True)"

run:
	$(PYTHON) uvicorn app.main:app --reload
