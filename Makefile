.PHONY: fmt lint lint-sql smoke run watcher check-all doctor-dev doctor-prod demo-prod pipeline-demo-prod audit-env pre-deploy

PYTHON ?= python
POWERSHELL ?= $(shell if command -v pwsh >/dev/null 2>&1; then echo pwsh; else echo powershell; fi)

# Ironclad pre-deploy gate - run this BEFORE any production deploy
pre-deploy:
	@echo "==> Running Ironclad Pre-Deploy Gate"
	$(POWERSHELL) -NoProfile -ExecutionPolicy Bypass -File scripts/pre_deploy_check.ps1

fmt:
	python -m black . && python -m isort .

lint:
	flake8 . || true
	mypy --ignore-missing-imports || true

lint-sql:
	$(PYTHON) tools/sql_lint.py

smoke:
	python -m tools.smoke

run:
	python main.py

watcher:
	python main.py

# Railway environment audit - validates env contract before deploy
audit-env:
	@echo "==> Running Railway environment audit (all services)"
	$(PYTHON) scripts/railway_env_audit.py --check

audit-env-contract:
	@echo "==> Printing canonical environment contract"
	$(PYTHON) scripts/railway_env_audit.py --print-contract

check-all:
	python -m tools.db_check && \
	python -m tools.doctor && \
	python -m pytest -q && \
	(cd dragonfly-dashboard && npm run build)

doctor-dev:
	@echo "==> Running Supabase database check (dev)"
	$(PYTHON) -m tools.db_check --env dev
	@echo "==> Running Supabase doctor (dev)"
	$(PYTHON) -m tools.doctor --env dev

doctor-prod:
	@echo "==> Running production preflight checks"
	$(POWERSHELL) -NoProfile -ExecutionPolicy Bypass -File scripts/preflight_prod.ps1

demo-prod:
	@echo "==> Running production demo smoke sequence"
	$(POWERSHELL) -NoProfile -ExecutionPolicy Bypass -File scripts/demo_smoke_prod.ps1

pipeline-demo-prod:
	@echo "==> Running production demo pipeline"
	$(POWERSHELL) -NoProfile -ExecutionPolicy Bypass -File scripts/demo_pipeline_prod.ps1
