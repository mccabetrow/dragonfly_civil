.PHONY: fmt lint smoke run watcher

fmt:
	python -m black . && python -m isort .

lint:
	flake8 . || true
	mypy --ignore-missing-imports || true

smoke:
	python -m tools.smoke

run:
	python main.py

watcher:
	python main.py
