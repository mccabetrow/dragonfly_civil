# OPS Intake Gateway

Automated daily intake validation workflow for new lead verification.

## Overview

The OPS Intake Gateway is an n8n workflow that runs every morning at 10:00 AM to:

1. Fetch new candidate judgments from Supabase
2. Validate each lead using AI (name, address, case number format)
3. Store validation results for ops review
4. Notify ops via Discord/Slack
5. Update judgment status to "awaiting_ops_review"

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                      OPS_INTAKE_GATEWAY                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────┐    ┌─────────────┐    ┌───────────┐                   │
│  │  Cron    │───▶│   Fetch     │───▶│    AI     │                   │
│  │ 10:00 AM │    │ Candidates  │    │ Validate  │                   │
│  └──────────┘    └─────────────┘    └─────┬─────┘                   │
│                                           │                          │
│                                           ▼                          │
│  ┌──────────────┐    ┌─────────────┐    ┌───────────┐               │
│  │   Notify     │◀───│  Aggregate  │◀───│   Store   │               │
│  │ Discord/Slack│    │   Results   │    │  Results  │               │
│  └──────────────┘    └─────────────┘    └───────────┘               │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

## Database Schema

### New Enum Values: `judgment_status_enum`

```sql
'new_candidate'       -- Freshly imported leads
'awaiting_ops_review' -- AI-validated, pending human review
'ops_approved'        -- Human-verified, ready for enrichment
'ops_rejected'        -- Failed human verification
```

### New Enum: `intake_validation_result`

```sql
'valid'        -- All AI checks passed
'invalid'      -- One or more critical issues found
'needs_review' -- Ambiguous, requires human judgment
```

### New Table: `intake_results`

| Column                   | Type                     | Description                          |
| ------------------------ | ------------------------ | ------------------------------------ |
| id                       | uuid                     | Primary key                          |
| judgment_id              | uuid                     | FK to core_judgments                 |
| validated_at             | timestamptz              | When AI validation ran               |
| validation_source        | text                     | Origin (default: n8n_intake_gateway) |
| result                   | intake_validation_result | Overall validation result            |
| name_check_passed        | boolean                  | Name validation result               |
| name_check_note          | text                     | AI explanation                       |
| address_check_passed     | boolean                  | Address validation result            |
| address_check_note       | text                     | AI explanation                       |
| case_number_check_passed | boolean                  | Case number validation result        |
| case_number_check_note   | text                     | AI explanation                       |
| confidence_score         | int                      | AI confidence (0-100)                |
| ai_response              | jsonb                    | Raw AI response for debugging        |
| reviewed_by              | uuid                     | Auth user who reviewed               |
| reviewed_at              | timestamptz              | When human review occurred           |
| review_decision          | text                     | 'approved', 'rejected', 'flagged'    |
| review_notes             | text                     | Human reviewer notes                 |

### New View: `v_intake_queue`

Dashboard-ready view joining `core_judgments` with latest `intake_results`:

- Shows all `new_candidate` and `awaiting_ops_review` judgments
- Includes AI validation details and human review status
- Sorted by review priority (needs_review first, then valid, then invalid)

## RPC Endpoints

### `fetch_new_candidates(limit)`

Fetches judgments needing validation. Used by n8n.

```sql
SELECT * FROM public.fetch_new_candidates(100);
```

### `store_intake_validation(...)`

Stores AI validation results. Used by n8n.

```sql
SELECT public.store_intake_validation(
    _judgment_id := 'uuid',
    _result := 'valid',
    _confidence_score := 85,
    _name_check_passed := true,
    _name_check_note := 'Valid personal name',
    _address_check_passed := true,
    _address_check_note := 'Physical address detected',
    _case_number_check_passed := true,
    _case_number_check_note := 'Valid format: 12345/2023',
    _ai_response := '{"raw": "response"}'::jsonb
);
```

### `submit_intake_review(...)`

Submits human review decision. Used by dashboard.

```sql
SELECT public.submit_intake_review(
    _validation_id := 'uuid',
    _decision := 'approved',
    _notes := 'Verified against court records'
);
```

### `get_intake_stats()`

Returns intake queue statistics. Used by dashboard.

```sql
SELECT public.get_intake_stats();
-- Returns: {
--   "new_candidates": 5,
--   "awaiting_review": 12,
--   "approved_today": 8,
--   "rejected_today": 2,
--   "validation_results": { "valid": 10, "invalid": 3, "needs_review": 4 },
--   "pending_human_review": 17,
--   "generated_at": "2025-12-02T10:00:00Z"
-- }
```

## n8n Workflow Setup

### 1. Import the Workflow

Import `n8n/flows/OPS_INTAKE_GATEWAY.json` into your n8n instance.

### 2. Configure Credentials

1. **Supabase API**: Create a credential with your project URL and service_role key
2. **OpenAI API**: Create a credential with your OpenAI API key
3. **Discord Webhook** (optional): Create webhook in your Discord channel
4. **Slack Webhook** (optional): Create incoming webhook in your Slack workspace

### 3. Environment Variables

Set in n8n environment or workflow:

```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
OPENAI_API_KEY=your-openai-key
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

### 4. Enable the Workflow

Toggle the workflow to "Active" in n8n.

## Frontend Integration

### Route

The intake queue is accessible at `/ops/intake` in the dashboard.

### Components

- **OpsIntakePage** (`pages/OpsIntakePage.tsx`): Main page with stats and queue
- **OpsIntakeQueuePanel** (`components/ops/OpsIntakeQueuePanel.tsx`): Queue list with review actions

### Hooks

- **useIntakeQueue**: Fetches queue data from `v_intake_queue`
- **useIntakeStats**: Fetches statistics from `get_intake_stats()`
- **useSubmitIntakeReview**: Submits review decisions via `submit_intake_review()`

### Adding to Navigation

Add to the sidebar navigation in `AppShellNew.tsx`:

```tsx
{
  icon: FileCheck,
  label: 'Intake Queue',
  to: '/ops/intake',
  badge: intakeStats.pendingHumanReview > 0
    ? intakeStats.pendingHumanReview
    : undefined,
}
```

## AI Validation Criteria

The AI validates each lead against these criteria:

### 1. Name Check

- Is the debtor_name a valid-looking personal or business name?
- Rejects: gibberish, obviously fake names (John Doe, Test User, ZZZZZ)

### 2. Address Check

- Does the address appear to NOT be a PO Box?
- We need a physical address for service of process

### 3. Case Number Check

- Does the case_index_number follow a valid court format?
- Expected formats: `12345/2023`, `CV-2023-001234`, etc.

## Workflow Status Flow

```
Import (new_candidate)
        │
        ▼
┌───────────────────┐
│  AI Validation    │ (10:00 AM daily)
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ awaiting_ops_review│
└─────────┬─────────┘
          │
    ┌─────┴─────┐
    │           │
    ▼           ▼
┌────────┐  ┌────────┐
│approved│  │rejected│
│        │  │        │
└────┬───┘  └────────┘
     │
     ▼
ops_approved → unsatisfied → enrichment pipeline
```

## RLS Policies

The `intake_results` table has strict RLS:

- **SELECT**: admin, ops, service_role
- **INSERT**: service_role only (n8n)
- **UPDATE**: admin, ops (for review fields only)

## Deployment

1. Apply the migration:

   ```powershell
   # Dev
   ./scripts/db_push.ps1 -SupabaseEnv dev

   # Prod
   ./scripts/db_push.ps1 -SupabaseEnv prod
   ```

2. Import the n8n workflow and configure credentials

3. Rebuild the dashboard:

   ```bash
   cd dragonfly-dashboard
   npm run build
   ```

4. Enable the n8n workflow

## Monitoring

- Check n8n execution history for daily runs
- Monitor `intake_results` table for validation trends
- Use `get_intake_stats()` RPC for dashboard statistics
- Discord/Slack alerts for daily summary
