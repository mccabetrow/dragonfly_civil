# Makefile for Dragonfly project

PYTHON ?= python

.PHONY: validate publish env.copy db.push db.reset db.diff types.gen sql.fmt score.sample enrich.sample test entities reload n8n.up n8n.down n8n.logs n8n.import n8n.export stubs.run db.migrate db.migrate-all doctor smoke db.fix-versions

validate:
	python -m validate_simplicity

publish:
	powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File scripts/publish.ps1

env.copy:
	@test -f .env || cp .env.example .env

db.push:
	supabase db push

db.reset:
	supabase db reset --force

db.diff:
	supabase db diff --linked

types.gen:
	python -c "import pathlib; pathlib.Path('app_types').mkdir(parents=True, exist_ok=True)"
	supabase gen types typescript --project-id $$SUPABASE_PROJECT_REF > app_types/supabase.ts

sql.fmt:
	@if command -v psqlfmt >/dev/null 2>&1; then \
		for file in $$(find supabase/migrations -name '*.sql'); do \
			psqlfmt --write $$file; \
		done; \
	else \
		echo "psqlfmt not found; skipping sql formatting"; \
	fi

score.sample:
	python -m src.workers.score_cases --limit 25

enrich.sample:
	python -m src.workers.enrich_bundle

test:
	$(PYTHON) -m pytest -q

entities:
	$(PYTHON) -c "import os, uuid, json, httpx; from dotenv import load_dotenv; load_dotenv(); base = os.environ['SUPABASE_URL'].rstrip('/'); key = os.environ['SUPABASE_ANON_KEY']; headers = {'apikey': key, 'Authorization': f'Bearer {key}', 'Content-Type': 'application/json', 'Accept': 'application/json', 'Prefer': 'return=representation'}; case_number = f'SMOKE-MAKE-{uuid.uuid4().hex[:6].upper()}'; payload = {'payload': {'case': {'case_number': case_number, 'source': 'make', 'title': 'Auto v. Make', 'court': 'NYC Civil Court'}, 'entities': [{'role': 'plaintiff', 'name_full': 'Makefile Plaintiff', 'emails': ['make@example.com']}, {'role': 'defendant', 'name_full': 'Makefile Defendant', 'phones': ['555-0199']}]}}; response = httpx.post(f'{base}/rest/v1/rpc/insert_case_with_entities', headers=headers, json=payload, timeout=30); response.raise_for_status(); data = response.json(); data = data[0] if isinstance(data, list) and data else data; print(json.dumps({'case_number': case_number, 'case_id': data.get('case_id'), 'entity_ids': data.get('entity_ids')}, indent=2))"

reload:
	powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "\
		$ErrorActionPreference = 'Stop'; \
		$base = $${env:SUPABASE_URL}.TrimEnd('/'); \
		$key = $${env:SUPABASE_SERVICE_ROLE_KEY}; \
		if (-not $base -or -not $key) { throw 'Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY'; } \
		$uri = \"$base/rest/v1/rpc/pgrst_reload\"; \
		$headers = @{ apikey = $key; Authorization = \"Bearer $key\"; Accept = 'application/json' }; \
		Invoke-RestMethod -Method Post -Uri $uri -Headers $headers | Out-Null; \
		Write-Host 'PostgREST reload requested.'"

n8n.up:
	cd ops/n8n && cp -n .env.example .env && docker compose up -d

n8n.down:
	cd ops/n8n && docker compose down -v

n8n.logs:
	cd ops/n8n && docker compose logs -f --tail=200 n8n

n8n.import:
	@echo "Open http://localhost:5678 -> Import -> choose ops/n8n/dragonfly_core_v25.json"

n8n.export:
	@echo "Use UI to export the workflow after edits. (API scripting optional)"

stubs.run:
	uvicorn ops.stubs.server:app --reload --port 5100

db.migrate:
	powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File scripts/db_push.ps1

db.migrate-all:
	powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File scripts/db_push.ps1 -IncludeAll

doctor:
	$(PYTHON) -m tools.doctor

smoke:
	$(PYTHON) -m tools.doctor && \
	$(PYTHON) -m src.workers.enrich_bundle && \
	$(PYTHON) -m src.workers.score_cases --limit 5 && \
	$(PYTHON) -m pytest -q

db.fix-versions:
	powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File scripts/fix_migration_versions.ps1
