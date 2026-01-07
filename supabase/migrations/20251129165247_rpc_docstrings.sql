-- RPC Docstring Comments
-- Adds PostgreSQL COMMENT metadata to critical RPCs for API documentation.
-- These comments are visible via pg_catalog and help document the RPC contract.
BEGIN;
--------------------------------------------------------------------------------
-- insert_or_get_case: Idempotent case lookup/insert
--------------------------------------------------------------------------------
COMMENT ON FUNCTION public.insert_or_get_case(jsonb) IS $docstring$ Idempotent case
    lookup
    or insertion by (case_number, source).INPUTS (payload jsonb): { "case_number": string (required, uppercased, trimmed internally) "source": string (default: "unknown") "org_id": uuid (default: nil UUID) "court": string (optional) "title": string (optional) "amount_awarded": numeric (optional) "judgment_date": date (optional) } OUTPUTS: uuid - the case_id (
        existing
        or newly created
    ) IDEMPOTENCY: - Looks up by (upper(trim(case_number)), source, org_id) - Returns existing case_id if found - Handles unique_violation race conditions gracefully - Calling twice with identical payload returns same case_id SECURITY: - SECURITY DEFINER (runs as owner) - Restricted to service_role Example:
    SELECT public.insert_or_get_case(
            '{"case_number": "CV-2024-001", "source": "vendor_x"}'::jsonb
        );
$docstring$;
--------------------------------------------------------------------------------
-- insert_or_get_case_with_entities: Idempotent case+entity bundle insertion
--------------------------------------------------------------------------------
COMMENT ON FUNCTION public.insert_or_get_case_with_entities(jsonb) IS $docstring$ Idempotent case
    + entity bundle insertion via insert_or_get_case + entity loop.INPUTS (payload jsonb): { "case": { "case_number": string (required) "source": string (default: "unknown") "org_id": uuid (optional) "court": string (optional) "title": string (optional) "amount_awarded": numeric (optional) "judgment_date": date (optional) },
    "entities": [
      {
        "role": "plaintiff"|"defendant"|... (required)
        "name_full": string (required)
        "name_normalized": string (optional, computed if missing)
        ... additional entity fields
      }
    ] } OUTPUTS: jsonb { "case_id": uuid "case_number": string "source": string "court": string "title": string "amount_awarded": numeric "judgment_date": date "case": {...same fields...} "entities": [ { "entity_id", "role", "name_full", "name_normalized" } ] "entity_ids": [ uuid, ... ] "meta": { "inserted_entities": int } } IDEMPOTENCY: - Case
: deduplicated by (case_number, source) - Entities: deduplicated by (case_id, role, name_normalized) - Second call with identical payload returns same case_id
        and entity_ids - No duplicate rows created in judgments.cases
        or parties.entities SECURITY: - SECURITY DEFINER (runs as owner) - Restricted to service_role Example:
        SELECT *
        FROM public.insert_or_get_case_with_entities(
                '{
    "case": {"case_number": "CV-2024-001", "source": "vendor_x"},
    "entities": [
      {"role": "plaintiff", "name_full": "Acme Corp"},
      {"role": "defendant", "name_full": "John Doe"}
    ]
  }'::jsonb
            );
$docstring$;
--------------------------------------------------------------------------------
-- queue_job: Enqueue a job to the pgmq-backed task queue
--------------------------------------------------------------------------------
COMMENT ON FUNCTION public.queue_job(jsonb) IS $docstring$ Enqueue a job to the pgmq - backed dragonfly_tasks queue.INPUTS (payload jsonb): { "kind": string (required) - one of: - "enrich": Run enrichment pipeline - "outreach": Schedule outreach actions - "enforce": Execute enforcement logic - "case_copilot": AI case
    analysis - "collectability": Score collectability - "escalation": Escalation workflow "idempotency_key": string (required, non - empty) - unique job identifier "payload": object (optional) - job - specific data passed to worker } OUTPUTS: bigint - the pgmq message_id IDEMPOTENCY: WARNING: This RPC is NOT idempotent at the DB level.- Each call creates a new message in the queue - Idempotency is enforced by downstream workers tracking processed keys - Workers should check idempotency_key before processing VALIDATION: - Raises exception if kind is not in allowed list - Raises exception if idempotency_key is missing
    or empty SECURITY: - SECURITY DEFINER (runs as owner) - Restricted to service_role Example:
    SELECT public.queue_job(
            '{
    "kind": "enforce",
    "idempotency_key": "enforce:case:123e4567-e89b-12d3-a456-426614174000",
    "payload": {"case_id": "123e4567-e89b-12d3-a456-426614174000"}
  }'::jsonb
        );
$docstring$;
--------------------------------------------------------------------------------
-- upsert_enrichment_bundle: Idempotent enrichment data upsert
--------------------------------------------------------------------------------
COMMENT ON FUNCTION public.upsert_enrichment_bundle(jsonb) IS $docstring$ Upsert enrichment contacts
and assets for a case
    with idempotent behavior.INPUTS (bundle jsonb): { "case_id": uuid (required) "contacts": [
      {
        "entity_id": uuid (required)
        "kind": "phone"|"email"|"address" (required)
        "value": string (required)
        "source": string (optional)
        "score": numeric (optional)
        "validated_bool": boolean (optional, default false)
      }
    ],
    "assets": [
      {
        "entity_id": uuid (required)
        "asset_type": string (required)
        "meta_json": object (optional)
        "source": string (optional)
        "confidence": numeric (optional)
      }
    ] } OUTPUTS: jsonb { "contacts_upserted": int "assets_upserted": int } IDEMPOTENCY: - Contacts: UPSERT by (entity_id, kind, value) - ON CONFLICT: updates source,
    score,
    validated_bool,
    updated_at - Assets: UPSERT by (entity_id, asset_type, hash of meta_json) - ON CONFLICT: updates source,
    confidence,
    updated_at - Second call with same data updates existing rows,
    does not duplicate - Row counts remain stable
    after repeated calls SECURITY: - SECURITY DEFINER (runs as owner) - Restricted to service_role Example:
    SELECT *
    FROM public.upsert_enrichment_bundle(
            '{
    "case_id": "123e4567-e89b-12d3-a456-426614174000",
    "contacts": [
      {"entity_id": "...", "kind": "phone", "value": "555-0100", "score": 0.9}
    ],
    "assets": []
  }'::jsonb
        );
$docstring$;
--------------------------------------------------------------------------------
-- dequeue_job: Pop the next job from the queue for processing
--------------------------------------------------------------------------------
COMMENT ON FUNCTION public.dequeue_job(text) IS $docstring$ Dequeue the next job
from the pgmq - backed dragonfly_tasks queue.INPUTS: p_kind: text (required) - filter by job kind,
    or 'any' for all kinds OUTPUTS: jsonb - the job payload including: { "msg_id": bigint "kind": string "idempotency_key": string "payload": object "enqueued_at": timestamp } Returns NULL if no jobs available BEHAVIOR: - Pops one message
from the queue (destructive read) - Workers should acknowledge
    or archive
after processing - Use visibility timeout for at - least - once delivery SECURITY: - SECURITY DEFINER (runs as owner) - Restricted to service_role Example:
SELECT *
FROM public.dequeue_job('enforce');
$docstring$;
COMMIT;
