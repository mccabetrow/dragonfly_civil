# Dragonfly

Civil-judgment enforcement automation system.

## Supabase Quickstart

1. **Activate virtualenv**

	```powershell
	.\.venv\Scripts\Activate.ps1
	```

2. **Load environment variables**

	```powershell
	.\scripts\load_env.ps1
	```

3. **Apply SQL (if needed) and reload PostgREST**

	Paste any SQL directly into the Supabase SQL Editor, then reload the API:

	```powershell
	$BASE=$env:SUPABASE_URL; $K=$env:SUPABASE_SERVICE_ROLE_KEY
	Invoke-RestMethod -Method Post -Uri ($BASE.TrimEnd('/') + '/rest/v1/rpc/pgrst_reload') -Headers @{apikey=$K; Authorization="Bearer $K"} | Out-Null
	```

4. **Insert the demo composite bundle (idempotent)**

	```powershell
	python -m etl.src.collector_v1 --composite --use-idempotent-composite --case-number SMOKE-DEMO-0001
	```

5. **Tail the ingestion audit view**

	```powershell
	Invoke-RestMethod -Uri "$BASE/rest/v1/v_ingestion_runs?select=run_id,event,source_code,ref_id,created_at&limit=5" -Headers @{apikey=$K; Authorization="Bearer $K"}
	```

### Public REST surface toggle

Set `USE_PUBLIC_WRAPPERS=true` to use `/rest/v1/public.v_*` plus public RPC wrappers (no dashboard changes required).
Set `USE_PUBLIC_WRAPPERS=false` to call schema-backed endpoints directly (requires exposing schemas in Supabase API settings).

## Front Door (Cases + Entities)

**.env keys**
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_PROJECT_REF`

**Link, push, reload**
```bash
supabase link --project-ref $SUPABASE_PROJECT_REF
make db.push
make reload
```

**Collector smoke insert**
```bash
python -m etl.collector_v1 --case --entity --composite
```

**Composite RPC (Python)**
```bash
python - <<'PY'
import os, json, httpx, uuid
from dotenv import load_dotenv

load_dotenv()
base = os.environ['SUPABASE_URL'].rstrip('/')
key = os.environ['SUPABASE_ANON_KEY']
headers = {
	'apikey': key,
	'Authorization': f'Bearer {key}',
	'Content-Type': 'application/json',
	'Prefer': 'return=representation',
}
case_number = f'SMOKE-COMPOSITE-{uuid.uuid4().hex[:6].upper()}'
payload = {
	'payload': {
		'case': {
			'case_number': case_number,
			'source': 'python',
			'title': 'Alpha v. Beta',
			'court': 'NYC Civil Court',
		},
		'entities': [
			{'role': 'plaintiff', 'name_full': 'Plaintiff One', 'emails': ['p1@example.com']},
			{'role': 'defendant', 'name_full': 'Defendant One', 'phones': ['555-0100']},
		],
	}
}
resp = httpx.post(f"{base}/rest/v1/rpc/insert_case_with_entities", headers=headers, json=payload, timeout=30)
resp.raise_for_status()
print(json.dumps(resp.json(), indent=2))
PY
```

**Composite RPC (n8n)**
- Import `docs/n8n_insert_case_with_entities.json`
- Configure env vars `SUPABASE_URL` and `SUPABASE_ANON_KEY`
- Execute the HTTP Request node
