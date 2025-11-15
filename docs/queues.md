# Queue Architecture

Dragonfly uses the `pgmq` extension to power three logical queues:

- `q_enrich`
- `q_outreach`
- `q_enforce`

Each enqueue request supplies a `kind` value that routes jobs to one of these queues. Internally, the `queue_job` RPC maps each kind directly to its corresponding pgmq queue.

## `queue_job` RPC Contract

- Signature: `public.queue_job(payload jsonb) returns bigint`
- Purpose: push a job onto the correct pgmq queue and return the message id.

Expected JSON body (`payload` argument):

| Field             | Type                                | Notes                                 |
| ----------------- | ----------------------------------- | -------------------------------------- |
| `idempotency_key` | string (required)                   | Rejects missing or empty values.       |
| `kind`            | `"enrich" \| "outreach" \| "enforce"` | Any other value raises an exception.   |
| `payload`         | object                              | Job-specific data stored verbatim.     |

Validation rules enforced by the RPC:

- Missing `kind` → `queue_job: missing kind in payload`
- `kind` not in {`enrich`, `outreach`, `enforce`} → `queue_job: unsupported kind <value>`
- Missing or empty `idempotency_key` → `queue_job: missing idempotency_key`

## Example PostgREST Call

```bash
curl -X POST \
  "$SUPABASE_URL/rest/v1/rpc/queue_job" \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "idempotency_key": "doctor:ping",
    "kind": "enrich",
    "payload": {}
  }'
```

## Health Checks and Migrations

- Migration `0051_queue_job_expose.sql` defines the single-jsonb `queue_job` RPC and grants it to PostgREST roles.
- Migration `0052_queue_bootstrap.sql` creates the backing pgmq queues (`q_enrich`, `q_outreach`, `q_enforce`).
- Run `tools/doctor.py` to confirm the RPC is visible to PostgREST and the pgmq queues exist. The doctor script surfaces actionable messages for missing migrations, absent queues, or network issues.
