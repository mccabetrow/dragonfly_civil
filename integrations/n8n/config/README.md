# Dragonfly n8n Workflows

## Secrets to set
- `SUPABASE_REF`
- `SUPABASE_SERVICE_ROLE_KEY`
- `PDL_API_KEY`
- `APOLLO_API_KEY`
- `WHITEPAGES_API_KEY`
- `LOB_API_KEY`
- `TWILIO_SID`
- `TWILIO_AUTH`
- `POSTMARK_KEY`
- `DRY_RUN`

| Field | Purpose |
| --- | --- |
| `SUPABASE_REF` | Supabase project reference (e.g. `abcd1234`) used to build REST/RPC URLs. |
| `SUPABASE_SERVICE_ROLE_KEY` | Service-role key for authenticated Supabase REST/RPC calls. |
| `PDL_API_KEY` | Key for People Data Labs enrichment lookups. |
| `APOLLO_API_KEY` | Key for Apollo enrichment requests. |
| `WHITEPAGES_API_KEY` | Key for Whitepages Pro lookups. |
| `LOB_API_KEY` | API token for Lob print & mail automation. |
| `TWILIO_SID` | Twilio Account SID for messaging API calls. |
| `TWILIO_AUTH` | Twilio auth token paired with the SID (used for HTTP Basic). |
| `POSTMARK_KEY` | Postmark server token for email delivery. |
| `DRY_RUN` | When `true`, vendor requests target the local stub server (`make stubs.run`). |

## Import instructions
1. Open the n8n editor and choose **Import from File**.
2. Select `ops/n8n/dragonfly_core_v25.json` from this repository.
3. Review each HTTP, Postgres, and Supabase node to map the listed secrets to n8n credentials (or environment variables).
4. Update the placeholder localhost URLs with the correct service endpoints for your environment.
5. Activate the workflow when ready.

## Export your workflow ID
1. Open the workflow in the n8n editor.
2. Look at the browser URL: `http://localhost:5678/workflow/<workflowId>`.
3. Copy the `<workflowId>` portion for use in API scripts or automation.

## Local start
- `make n8n.up`
- Open http://localhost:5678
- Default credentials: `admin` / `admin123` (change in `.env`)

