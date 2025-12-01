# Workflow: New Lead Enrichment

> **File**: `n8n/flows/dragonfly_new_lead_enrichment_v1.json`  
> **Trigger**: Supabase Trigger on `public.core_judgments` INSERT where `status = 'unsatisfied'`  
> **Purpose**: Automatically enrich new judgment records with debtor intelligence and update status to `ACTIONABLE` when confidence is high enough.

---

## Overview

This workflow fires whenever a new judgment is inserted into `public.core_judgments` with status `'unsatisfied'` (the default for new rows). It:

1. Fetches the full judgment record.
2. Decides which enrichment tier to call based on `principal_amount`.
3. Calls an external enrichment API (placeholder for idiCORE/TLOxp).
4. Parses the raw JSON response using an AI node with a strict schema.
5. Validates the AI output—on failure, sends a Discord alert and leaves the judgment unchanged.
6. On success, inserts a `debtor_intelligence` record and updates the judgment status to `'ACTIONABLE'` if `confidence_score ≥ 60`.
7. Posts a Discord summary for the new actionable lead.

---

## Node-by-Node Breakdown

### 1. Supabase Trigger (Webhook)

**Node Type**: `n8n-nodes-base.supabaseTrigger`  
**Name**: `New Judgment Trigger`

> **Note**: If using Supabase webhooks instead of the native trigger node, configure a Postgres `AFTER INSERT` trigger that calls a webhook URL. The native Supabase Trigger node listens for database events via Realtime.

**Configuration**:

| Field  | Value                   |
| ------ | ----------------------- |
| Event  | `INSERT`                |
| Schema | `public`                |
| Table  | `core_judgments`        |
| Filter | `status=eq.unsatisfied` |

**Output JSON** (example):

```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "case_index_number": "2024-NY-12345",
  "debtor_name": "John Q. Debtor",
  "original_creditor": "Acme Collections LLC",
  "judgment_date": "2024-06-15",
  "principal_amount": 8500.0,
  "interest_rate": 9.0,
  "court_name": "Civil Court of the City of New York",
  "county": "Kings",
  "status": "unsatisfied",
  "collectability_score": null,
  "created_at": "2024-11-30T14:00:00Z",
  "updated_at": "2024-11-30T14:00:00Z"
}
```

---

### 2. Fetch Judgment Details

**Node Type**: `n8n-nodes-base.supabase`  
**Name**: `Fetch Judgment`

**Configuration**:

| Field     | Value                        |
| --------- | ---------------------------- |
| Operation | `Select`                     |
| Schema    | `public`                     |
| Table     | `core_judgments`             |
| Return    | `All matching rows`          |
| Filters   | `id` equals `{{ $json.id }}` |

> This ensures we have the full record with all columns, even if the trigger only sends partial data.

**Output**: Same structure as trigger output but guaranteed complete.

---

### 3. Decide Enrichment Tier

**Node Type**: `n8n-nodes-base.code`  
**Name**: `Decide Enrichment Tier`

**Purpose**: Select which enrichment API tier to call based on `principal_amount`:

- **Tier 1 (Basic)**: `principal_amount < 2000` — Skip enrichment, set status to `'low_value'`.
- **Tier 2 (Standard)**: `2000 ≤ principal_amount < 10000` — Call standard enrichment.
- **Tier 3 (Premium)**: `principal_amount ≥ 10000` — Call premium enrichment with deeper asset search.

**JavaScript Code**:

```javascript
const judgment = $input.first().json;
const amount = parseFloat(judgment.principal_amount) || 0;

let tier, endpoint, skipEnrichment;

if (amount < 2000) {
  tier = "skip";
  endpoint = null;
  skipEnrichment = true;
} else if (amount < 10000) {
  tier = "standard";
  endpoint = "https://api.example.com/enrich/standard";
  skipEnrichment = false;
} else {
  tier = "premium";
  endpoint = "https://api.example.com/enrich/premium";
  skipEnrichment = false;
}

return [
  {
    json: {
      ...judgment,
      enrichment_tier: tier,
      enrichment_endpoint: endpoint,
      skip_enrichment: skipEnrichment,
    },
  },
];
```

**Output**:

```json
{
  "id": "a1b2c3d4-...",
  "debtor_name": "John Q. Debtor",
  "principal_amount": 8500.0,
  "enrichment_tier": "standard",
  "enrichment_endpoint": "https://api.example.com/enrich/standard",
  "skip_enrichment": false
}
```

---

### 4. IF: Skip Low-Value Judgments

**Node Type**: `n8n-nodes-base.if`  
**Name**: `Skip Low Value?`

**Configuration**:

| Condition | Value                                       |
| --------- | ------------------------------------------- |
| Boolean   | `{{ $json.skip_enrichment }}` equals `true` |

**True Branch** → Node 4a: Update Status to `low_value` and end.  
**False Branch** → Continue to enrichment.

---

### 4a. Update Low-Value Status (True Branch)

**Node Type**: `n8n-nodes-base.supabase`  
**Name**: `Mark Low Value`

**Configuration**:

| Field     | Value                        |
| --------- | ---------------------------- |
| Operation | `Update`                     |
| Schema    | `public`                     |
| Table     | `core_judgments`             |
| Columns   | `status` = `low_value`       |
| Filter    | `id` equals `{{ $json.id }}` |

> Workflow ends here for low-value judgments.

---

### 5. Call Enrichment API

**Node Type**: `n8n-nodes-base.httpRequest`  
**Name**: `Call Enrichment API`

**Configuration**:

| Field             | Value                             |
| ----------------- | --------------------------------- |
| Method            | `POST`                            |
| URL               | `{{ $json.enrichment_endpoint }}` |
| Authentication    | `Header Auth` (API key)           |
| Body Content Type | `JSON`                            |
| Body              | See below                         |

**Request Body**:

```json
{
  "judgment_id": "{{ $json.id }}",
  "debtor_name": "{{ $json.debtor_name }}",
  "case_number": "{{ $json.case_index_number }}",
  "county": "{{ $json.county }}",
  "state": "NY",
  "request_type": "{{ $json.enrichment_tier }}"
}
```

**Headers**:

```json
{
  "Content-Type": "application/json",
  "X-API-Key": "{{ $credentials.enrichmentApiKey }}"
}
```

**Options**:

| Field         | Value                |
| ------------- | -------------------- |
| Retry on Fail | `true`               |
| Max Attempts  | `3`                  |
| Timeout       | `30000` (30 seconds) |

**Expected Response** (raw from vendor):

```json
{
  "status": "success",
  "data": {
    "person": {
      "name": "John Q. Debtor",
      "employer": "ABC Manufacturing Inc.",
      "employer_address": "123 Industrial Way, Brooklyn, NY 11201",
      "estimated_income": "$50,000 - $75,000",
      "bank": "Chase Bank",
      "bank_branch_address": "456 Main St, Brooklyn, NY 11215",
      "owns_home": true,
      "ssdi_recipient": false
    },
    "confidence": 0.78,
    "sources": ["credit_header", "employer_verification"]
  }
}
```

---

### 6. AI Parser: Extract Structured Intelligence

**Node Type**: `n8n-nodes-base.openAi` (or `@n8n/n8n-nodes-langchain.lmChatOpenAi`)  
**Name**: `AI Parse Enrichment`

**Purpose**: Transform vendor-specific JSON into our standardized `debtor_intelligence` schema.

**Configuration**:

| Field       | Value                                           |
| ----------- | ----------------------------------------------- |
| Operation   | `Chat`                                          |
| Model       | `gpt-4o-mini` (or `gpt-4o` for higher accuracy) |
| Max Tokens  | `500`                                           |
| Temperature | `0` (deterministic)                             |

**System Prompt**:

```text
You are a data extraction assistant for a judgment enforcement system.

Your task is to extract structured debtor intelligence from raw enrichment API responses.

ALWAYS respond with valid JSON matching this exact schema:

{
  "employer_name": string | null,
  "employer_address": string | null,
  "income_band": string | null,  // e.g., "$25k-50k", "$50k-75k", "$75k-100k", "$100k+"
  "bank_name": string | null,
  "bank_address": string | null,
  "home_ownership": "owner" | "renter" | "unknown",
  "has_benefits_only_account": boolean,  // true if SSDI/SSI recipient with exempt funds
  "confidence_score": number  // 0-100 integer
}

Rules:
1. Convert confidence decimals (0.78) to integers (78).
2. Normalize income to standard bands: "$25k-50k", "$50k-75k", "$75k-100k", "$100k+".
3. If owns_home is true, set home_ownership to "owner"; if false, "renter"; otherwise "unknown".
4. If ssdi_recipient or ssi_recipient is true, set has_benefits_only_account to true.
5. If any field is missing or unclear, use null (except confidence_score, default to 0).
6. Do NOT include any text outside the JSON object.
```

**User Prompt**:

```text
Extract debtor intelligence from this enrichment response:

{{ JSON.stringify($json, null, 2) }}
```

**Expected Output**:

```json
{
  "employer_name": "ABC Manufacturing Inc.",
  "employer_address": "123 Industrial Way, Brooklyn, NY 11201",
  "income_band": "$50k-75k",
  "bank_name": "Chase Bank",
  "bank_address": "456 Main St, Brooklyn, NY 11215",
  "home_ownership": "owner",
  "has_benefits_only_account": false,
  "confidence_score": 78
}
```

---

### 7. Validate AI Output

**Node Type**: `n8n-nodes-base.code`  
**Name**: `Validate AI Output`

**Purpose**: Ensure the AI returned valid JSON with all required fields.

**JavaScript Code**:

````javascript
const judgment = $items("Decide Enrichment Tier")[0].json;
const rawAiOutput =
  $input.first().json.message?.content || $input.first().json.text || "";

let parsed;
let validationError = null;

try {
  // Extract JSON from AI response (handle markdown code blocks)
  let jsonStr = rawAiOutput;
  const jsonMatch = rawAiOutput.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (jsonMatch) {
    jsonStr = jsonMatch[1].trim();
  }

  parsed = JSON.parse(jsonStr);

  // Validate required fields
  if (typeof parsed.confidence_score !== "number") {
    validationError = "Missing or invalid confidence_score";
  }

  // Normalize confidence_score to 0-100 range
  if (parsed.confidence_score > 0 && parsed.confidence_score <= 1) {
    parsed.confidence_score = Math.round(parsed.confidence_score * 100);
  }

  // Validate home_ownership enum
  const validHomeOwnership = ["owner", "renter", "unknown"];
  if (
    parsed.home_ownership &&
    !validHomeOwnership.includes(parsed.home_ownership)
  ) {
    parsed.home_ownership = "unknown";
  }
} catch (e) {
  validationError = `JSON parse error: ${e.message}`;
  parsed = null;
}

return [
  {
    json: {
      judgment_id: judgment.id,
      judgment: judgment,
      ai_output: parsed,
      validation_error: validationError,
      is_valid: !validationError && parsed !== null,
    },
  },
];
````

**Output**:

```json
{
  "judgment_id": "a1b2c3d4-...",
  "judgment": {
    /* full judgment object */
  },
  "ai_output": {
    "employer_name": "ABC Manufacturing Inc.",
    "confidence_score": 78
    /* ... */
  },
  "validation_error": null,
  "is_valid": true
}
```

---

### 8. IF: Validation Passed?

**Node Type**: `n8n-nodes-base.if`  
**Name**: `Validation Passed?`

**Configuration**:

| Condition | Value                                |
| --------- | ------------------------------------ |
| Boolean   | `{{ $json.is_valid }}` equals `true` |

**True Branch** → Insert intelligence + update status  
**False Branch** → Send Discord alert

---

### 9a. Discord Alert: Validation Failed (False Branch)

**Node Type**: `n8n-nodes-base.discord`  
**Name**: `Alert: Enrichment Failed`

**Configuration**:

| Field       | Value                                  |
| ----------- | -------------------------------------- |
| Operation   | `Send Message`                         |
| Webhook URL | `{{ $credentials.discordWebhookUrl }}` |

**Message**:

```text
⚠️ **Enrichment Validation Failed**

**Judgment ID**: {{ $json.judgment_id }}
**Case Number**: {{ $json.judgment.case_index_number }}
**Debtor**: {{ $json.judgment.debtor_name }}
**Error**: {{ $json.validation_error }}

Status remains `unsatisfied` — manual review required.
```

> Workflow ends here for failed validations. The judgment status stays `unsatisfied` so it will be retried on the next sweep or manual intervention.

---

### 9b. Insert Debtor Intelligence (True Branch)

**Node Type**: `n8n-nodes-base.supabase`  
**Name**: `Insert Debtor Intelligence`

**Configuration**:

| Field     | Value                 |
| --------- | --------------------- |
| Operation | `Insert`              |
| Schema    | `public`              |
| Table     | `debtor_intelligence` |

**Columns**:

| Column                      | Value                                             |
| --------------------------- | ------------------------------------------------- |
| `judgment_id`               | `{{ $json.judgment_id }}`                         |
| `data_source`               | `n8n_enrichment_v1`                               |
| `employer_name`             | `{{ $json.ai_output.employer_name }}`             |
| `employer_address`          | `{{ $json.ai_output.employer_address }}`          |
| `income_band`               | `{{ $json.ai_output.income_band }}`               |
| `bank_name`                 | `{{ $json.ai_output.bank_name }}`                 |
| `bank_address`              | `{{ $json.ai_output.bank_address }}`              |
| `home_ownership`            | `{{ $json.ai_output.home_ownership }}`            |
| `has_benefits_only_account` | `{{ $json.ai_output.has_benefits_only_account }}` |
| `confidence_score`          | `{{ $json.ai_output.confidence_score }}`          |
| `is_verified`               | `false`                                           |

**Output**: Inserted row with `id`.

---

### 10. Decide New Judgment Status

**Node Type**: `n8n-nodes-base.code`  
**Name**: `Decide Judgment Status`

**Purpose**: Set status to `ACTIONABLE` only if confidence ≥ 60.

**JavaScript Code**:

```javascript
const input = $input.first().json;
const prevNode = $items("Validate AI Output")[0].json;
const confidence = prevNode.ai_output?.confidence_score || 0;

// Status enum values from migration 0200
// 'unsatisfied', 'partially_satisfied', 'satisfied', 'vacated', 'expired', 'on_hold'
// We'll use a custom status text for now; adjust if enum is extended

const newStatus = confidence >= 60 ? "unsatisfied" : "unsatisfied";
const isActionable = confidence >= 60;

return [
  {
    json: {
      judgment_id: prevNode.judgment_id,
      judgment: prevNode.judgment,
      intelligence: prevNode.ai_output,
      debtor_intelligence_id: input.id,
      confidence_score: confidence,
      is_actionable: isActionable,
      new_collectability_score: confidence, // Store in collectability_score column
    },
  },
];
```

> **Note**: The `judgment_status_enum` type includes `unsatisfied`, `partially_satisfied`, `satisfied`, `vacated`, `expired`, `on_hold`. To represent "ACTIONABLE", we update `collectability_score` to the confidence value. Judgments with `collectability_score ≥ 60` are considered actionable.

---

### 11. Update Judgment with Score

**Node Type**: `n8n-nodes-base.supabase`  
**Name**: `Update Judgment Score`

**Configuration**:

| Field     | Value                                 |
| --------- | ------------------------------------- |
| Operation | `Update`                              |
| Schema    | `public`                              |
| Table     | `core_judgments`                      |
| Filter    | `id` equals `{{ $json.judgment_id }}` |

**Columns**:

| Column                 | Value                                  |
| ---------------------- | -------------------------------------- |
| `collectability_score` | `{{ $json.new_collectability_score }}` |

---

### 12. IF: Is Actionable?

**Node Type**: `n8n-nodes-base.if`  
**Name**: `Is Actionable?`

**Configuration**:

| Condition | Value                                     |
| --------- | ----------------------------------------- |
| Boolean   | `{{ $json.is_actionable }}` equals `true` |

**True Branch** → Post Discord summary  
**False Branch** → End (low-confidence leads get no notification)

---

### 13. Discord: New Actionable Lead

**Node Type**: `n8n-nodes-base.discord`  
**Name**: `Notify: Actionable Lead`

**Configuration**:

| Field       | Value                                  |
| ----------- | -------------------------------------- |
| Operation   | `Send Message`                         |
| Webhook URL | `{{ $credentials.discordWebhookUrl }}` |

**Message**:

```text
🎯 **New Actionable Lead**

**Case**: {{ $json.judgment.case_index_number }}
**Debtor**: {{ $json.judgment.debtor_name }}
**Creditor**: {{ $json.judgment.original_creditor }}
**Amount**: ${{ $json.judgment.principal_amount.toLocaleString() }}
**County**: {{ $json.judgment.county }}

**Intelligence Summary**:
• Employer: {{ $json.intelligence.employer_name || 'Unknown' }}
• Income Band: {{ $json.intelligence.income_band || 'Unknown' }}
• Bank: {{ $json.intelligence.bank_name || 'Unknown' }}
• Home: {{ $json.intelligence.home_ownership }}
• Benefits-Only Account: {{ $json.intelligence.has_benefits_only_account ? 'Yes ⚠️' : 'No' }}

**Confidence Score**: {{ $json.confidence_score }}/100 ✅

Ready for enforcement planning.
```

---

## Complete Node Connections

```
[1] New Judgment Trigger
         │
         ▼
[2] Fetch Judgment
         │
         ▼
[3] Decide Enrichment Tier
         │
         ▼
[4] Skip Low Value? ──(true)──► [4a] Mark Low Value ──► END
         │
       (false)
         │
         ▼
[5] Call Enrichment API
         │
         ▼
[6] AI Parse Enrichment
         │
         ▼
[7] Validate AI Output
         │
         ▼
[8] Validation Passed? ──(false)──► [9a] Alert: Enrichment Failed ──► END
         │
       (true)
         │
         ▼
[9b] Insert Debtor Intelligence
         │
         ▼
[10] Decide Judgment Status
         │
         ▼
[11] Update Judgment Score
         │
         ▼
[12] Is Actionable? ──(false)──► END
         │
       (true)
         │
         ▼
[13] Notify: Actionable Lead ──► END
```

---

## Required Credentials

| Credential Name     | Type         | Used By             |
| ------------------- | ------------ | ------------------- |
| `Supabase Service`  | Supabase API | Nodes 2, 4a, 9b, 11 |
| `enrichmentApiKey`  | Header Auth  | Node 5              |
| `discordWebhookUrl` | Generic      | Nodes 9a, 13        |
| `OpenAI API`        | OpenAI API   | Node 6              |

---

## Error Handling Checklist

- [ ] **API timeout**: Node 5 retries 3x with backoff.
- [ ] **AI parse failure**: Node 7 catches JSON errors; Node 9a sends Discord alert.
- [ ] **Supabase write failure**: Enable "Continue on Fail" on insert nodes; add error branch to alert.
- [ ] **Missing judgment**: Node 2 returns empty → add IF node to check for data before proceeding.

---

## Testing Checklist

1. Insert a test judgment with `principal_amount = 500` → should mark as `low_value`.
2. Insert a test judgment with `principal_amount = 5000` → should call standard enrichment.
3. Insert a test judgment with `principal_amount = 15000` → should call premium enrichment.
4. Mock enrichment API to return invalid JSON → should trigger Discord alert.
5. Mock enrichment API to return valid data with `confidence = 45` → should NOT send actionable notification.
6. Mock enrichment API to return valid data with `confidence = 75` → should send actionable notification.

---

## Future Enhancements

1. **Replace dummy endpoint**: Swap `https://api.example.com/enrich/*` with actual idiCORE/TLOxp endpoints.
2. **Add rate limiting**: Insert a Wait node before API call to respect vendor rate limits.
3. **Retry low-confidence**: Queue a re-enrichment job after 7 days for leads with `40 ≤ confidence < 60`.
4. **FDCPA compliance**: Add time-of-day check before sending outreach notifications.
5. **Audit logging**: Insert a row into `enrichment_audit_log` for compliance tracking.

---

_Last updated: November 2024_
