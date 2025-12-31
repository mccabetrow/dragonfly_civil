# Intake Station UX Specification

**Version:** 1.0  
**Date:** 2025-12-30  
**Status:** Ready for Engineering

---

## Overview

The Intake Station is a single-page CSV upload interface that ingests plaintiff and judgment data into Dragonfly. It must communicate progress clearly, handle errors gracefully, and prevent duplicate batch processing.

---

## State Machine

```
┌─────────┐
│  IDLE   │◄────────────────────────────────────────┐
└────┬────┘                                         │
     │ [file selected]                              │
     ▼                                              │
┌─────────────┐                                     │
│  VALIDATING │──[invalid file]──► FAILED ─────────┤
└──────┬──────┘                                     │
       │ [valid + new]                              │
       │                                            │
       │ [valid + duplicate]──► DUPLICATE ─────────┤
       ▼                                            │
┌─────────────┐                                     │
│  UPLOADING  │──[network error]──► FAILED ────────┤
└──────┬──────┘                                     │
       │ [upload complete]                          │
       ▼                                            │
┌─────────────┐                                     │
│ PROCESSING  │──[fatal error]──► FAILED ──────────┤
└──────┬──────┘                                     │
       │                                            │
       ├──[all rows succeed]──► COMPLETED ─────────┤
       │                                            │
       └──[some rows fail]──► PARTIAL ─────────────┘
```

### State Definitions

| State        | Description                               | User Can Leave? |
| ------------ | ----------------------------------------- | --------------- |
| `IDLE`       | No file selected; awaiting upload         | N/A             |
| `VALIDATING` | Checking file format, headers, dedupe key | No (< 2s)       |
| `DUPLICATE`  | File hash matches existing batch          | Yes             |
| `UPLOADING`  | Sending file to server                    | Yes (cancel)    |
| `PROCESSING` | Server parsing rows, inserting records    | No              |
| `COMPLETED`  | All rows ingested successfully            | Yes             |
| `PARTIAL`    | Some rows failed; others succeeded        | Yes             |
| `FAILED`     | Fatal error; no rows ingested             | Yes             |

---

## UI Components by State

### 1. IDLE State

```
┌────────────────────────────────────────────────────────────────┐
│  📥  Intake Station                                            │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                                                          │  │
│  │     Drag & drop a CSV file here, or click to browse      │  │
│  │                                                          │  │
│  │     Accepted: .csv files up to 10 MB                     │  │
│  │                                                          │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  Recent Batches                                                │
│  ─────────────────────────────────────────────────────────────│
│  batch_2025-12-29_simplicity  │ 142 plaintiffs │ Completed    │
│  batch_2025-12-28_jbi         │  87 plaintiffs │ Partial (3)  │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

**Microcopy:**

- Dropzone: `Drag & drop a CSV file here, or click to browse`
- Subtext: `Accepted: .csv files up to 10 MB`
- Empty recent: `No recent batches`

---

### 2. VALIDATING State

```
┌────────────────────────────────────────────────────────────────┐
│  📥  Intake Station                                            │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  📄 simplicity_export_dec30.csv                          │  │
│  │                                                          │  │
│  │  ◐ Validating file...                                    │  │
│  │                                                          │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

**Microcopy:**

- Spinner + `Validating file...`

**Validation checks (run client-side):**

1. File extension is `.csv`
2. File size ≤ 10 MB
3. Required headers present (per vendor adapter)
4. Compute SHA-256 hash for dedupe check

---

### 3. DUPLICATE State

```
┌────────────────────────────────────────────────────────────────┐
│  📥  Intake Station                                            │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  📄 simplicity_export_dec30.csv                          │  │
│  │                                                          │  │
│  │  ⚠️  This file was already uploaded                      │  │
│  │                                                          │  │
│  │  Showing existing batch: batch_2025-12-30_simplicity     │  │
│  │  Uploaded: Dec 30, 2025 at 2:14 PM                       │  │
│  │                                                          │  │
│  │  ┌────────────────┐  ┌─────────────────────────────────┐ │  │
│  │  │  View Batch    │  │  Upload Anyway (force=true)     │ │  │
│  │  └────────────────┘  └─────────────────────────────────┘ │  │
│  │                                                          │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

**Microcopy:**

- Warning icon + `This file was already uploaded`
- `Showing existing batch: {batch_name}`
- `Uploaded: {timestamp}`
- Primary button: `View Batch`
- Secondary button: `Upload Anyway` (triggers `force=true`)

**Force Upload Confirmation Modal:**

```
┌─────────────────────────────────────────────────────────┐
│  ⚠️  Re-upload this file?                               │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  This will create a new batch even though an identical  │
│  file was previously uploaded. Use this only if:        │
│                                                         │
│  • The previous batch was deleted                       │
│  • You need to reprocess after a schema change          │
│                                                         │
│  ┌────────────┐  ┌─────────────────────────────────────┐│
│  │   Cancel   │  │   Yes, Create New Batch             ││
│  └────────────┘  └─────────────────────────────────────┘│
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

### 4. UPLOADING State

```
┌────────────────────────────────────────────────────────────────┐
│  📥  Intake Station                                            │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  📄 simplicity_export_dec30.csv (2.4 MB)                 │  │
│  │                                                          │  │
│  │  ████████████████░░░░░░░░░░░░░░░░  47%                   │  │
│  │                                                          │  │
│  │  Uploading... 1.1 MB of 2.4 MB                           │  │
│  │                                                          │  │
│  │                              ┌────────────┐              │  │
│  │                              │   Cancel   │              │  │
│  │                              └────────────┘              │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

**Microcopy:**

- Progress bar with percentage
- `Uploading... {uploaded} of {total}`
- Cancel button (destructive secondary)

---

### 5. PROCESSING State

```
┌────────────────────────────────────────────────────────────────┐
│  📥  Intake Station                                            │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  📄 simplicity_export_dec30.csv                          │  │
│  │                                                          │  │
│  │  ⏳ Processing batch...                                   │  │
│  │                                                          │  │
│  │  ┌─────────────────────────────────────────────────────┐ │  │
│  │  │  Rows parsed:       847 / 847                       │ │  │
│  │  │  Plaintiffs created:  142                           │ │  │
│  │  │  Judgments created:   312                           │ │  │
│  │  │  Skipped (existing):   89                           │ │  │
│  │  └─────────────────────────────────────────────────────┘ │  │
│  │                                                          │  │
│  │  Batch ID: batch_2025-12-30_simplicity                   │  │
│  │                                                          │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

**Microcopy:**

- Spinner + `Processing batch...`
- Live counters (updated via SSE or polling):
  - `Rows parsed: {n} / {total}`
  - `Plaintiffs created: {n}`
  - `Judgments created: {n}`
  - `Skipped (existing): {n}`
- `Batch ID: {batch_name}`

**Implementation Note:** Use Server-Sent Events for real-time progress. Fallback to 2-second polling if SSE unavailable.

---

### 6. COMPLETED State

```
┌────────────────────────────────────────────────────────────────┐
│  📥  Intake Station                                            │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                                                          │  │
│  │  ✅ Import Complete                                      │  │
│  │                                                          │  │
│  │  ┌─────────────────────────────────────────────────────┐ │  │
│  │  │                                                     │ │  │
│  │  │   PLAINTIFFS          JUDGMENTS                     │ │  │
│  │  │   ┌────────┐          ┌────────┐                    │ │  │
│  │  │   │  142   │          │  312   │                    │ │  │
│  │  │   │ created│          │ created│                    │ │  │
│  │  │   └────────┘          └────────┘                    │ │  │
│  │  │                                                     │ │  │
│  │  │   +89 plaintiffs matched existing records           │ │  │
│  │  │   +47 judgments matched existing records            │ │  │
│  │  │                                                     │ │  │
│  │  └─────────────────────────────────────────────────────┘ │  │
│  │                                                          │  │
│  │  Batch ID: batch_2025-12-30_simplicity                   │  │
│  │  Duration: 12.4 seconds                                  │  │
│  │                                                          │  │
│  │  ┌──────────────────┐  ┌──────────────────────────────┐  │  │
│  │  │  Upload Another  │  │  View in Plaintiffs Table    │  │  │
│  │  └──────────────────┘  └──────────────────────────────┘  │  │
│  │                                                          │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

**Microcopy:**

- `✅ Import Complete`
- Large stat cards: `{n} created` for Plaintiffs and Judgments
- Subtext: `+{n} plaintiffs matched existing records` / `+{n} judgments matched existing records`
- `Batch ID: {batch_name}`
- `Duration: {seconds} seconds`
- Primary: `View in Plaintiffs Table`
- Secondary: `Upload Another`

---

### 7. PARTIAL State (Some Rows Failed)

```
┌────────────────────────────────────────────────────────────────┐
│  📥  Intake Station                                            │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                                                          │  │
│  │  ⚠️  Import Completed with Errors                        │  │
│  │                                                          │  │
│  │  ┌─────────────────────────────────────────────────────┐ │  │
│  │  │                                                     │ │  │
│  │  │   PLAINTIFFS          JUDGMENTS        ERRORS       │ │  │
│  │  │   ┌────────┐          ┌────────┐       ┌────────┐   │ │  │
│  │  │   │  139   │          │  298   │       │   14   │   │ │  │
│  │  │   │ created│          │ created│       │  rows  │   │ │  │
│  │  │   └────────┘          └────────┘       └────────┘   │ │  │
│  │  │                                         (red bg)    │ │  │
│  │  └─────────────────────────────────────────────────────┘ │  │
│  │                                                          │  │
│  │  Top Errors (3 of 14)                                    │  │
│  │  ─────────────────────────────────────────────────────── │  │
│  │  Row 47:  Missing required field "defendant_name"        │  │
│  │  Row 112: Invalid date format "13/45/2025"               │  │
│  │  Row 203: Duplicate dedupe_key in same file              │  │
│  │                                                          │  │
│  │  ┌──────────────────────────────────────────────────────┐│  │
│  │  │  📥 Download Error Report (CSV)                      ││  │
│  │  └──────────────────────────────────────────────────────┘│  │
│  │                                                          │  │
│  │  Batch ID: batch_2025-12-30_simplicity                   │  │
│  │                                                          │  │
│  │  ┌──────────────────┐  ┌──────────────────────────────┐  │  │
│  │  │  Upload Another  │  │  View Successful Records     │  │  │
│  │  └──────────────────┘  └──────────────────────────────┘  │  │
│  │                                                          │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

**Microcopy:**

- `⚠️ Import Completed with Errors`
- Three stat cards: Plaintiffs, Judgments, Errors (error card has red/destructive background)
- `Top Errors ({shown} of {total})`
- Error format: `Row {n}: {error_message}`
- Download button: `📥 Download Error Report (CSV)`
- Primary: `View Successful Records`
- Secondary: `Upload Another`

**Error Report CSV Format:**

```csv
row_number,field,error_type,error_message,raw_value
47,defendant_name,missing_required,"Missing required field ""defendant_name""",""
112,judgment_date,invalid_format,"Invalid date format ""13/45/2025""","13/45/2025"
203,dedupe_key,duplicate,"Duplicate dedupe_key in same file","SMITH-JOHN-1985-01-15"
```

---

### 8. FAILED State (Fatal Error)

```
┌────────────────────────────────────────────────────────────────┐
│  📥  Intake Station                                            │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                                                          │  │
│  │  ❌ Import Failed                                        │  │
│  │                                                          │  │
│  │  No records were created.                                │  │
│  │                                                          │  │
│  │  ┌─────────────────────────────────────────────────────┐ │  │
│  │  │  Error: Unable to parse CSV file. The file          │ │  │
│  │  │  appears to use semicolon delimiters instead of     │ │  │
│  │  │  commas. Please re-export with comma delimiters.    │ │  │
│  │  └─────────────────────────────────────────────────────┘ │  │
│  │                                                          │  │
│  │  If this error persists, contact support with:           │  │
│  │  Batch ID: batch_2025-12-30_simplicity                   │  │
│  │  Error Code: PARSE_DELIMITER_MISMATCH                    │  │
│  │                                                          │  │
│  │  ┌──────────────────┐                                    │  │
│  │  │  Try Again       │                                    │  │
│  │  └──────────────────┘                                    │  │
│  │                                                          │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

**Microcopy:**

- `❌ Import Failed`
- `No records were created.`
- Error box with user-friendly explanation
- Support block: `If this error persists, contact support with:`
  - `Batch ID: {batch_name}`
  - `Error Code: {code}`
- Primary: `Try Again` (resets to IDLE)

**Common Error Codes:**

| Code                       | User Message                                                |
| -------------------------- | ----------------------------------------------------------- |
| `PARSE_DELIMITER_MISMATCH` | The file uses semicolon delimiters instead of commas.       |
| `PARSE_ENCODING_ERROR`     | The file encoding is not UTF-8. Please re-export as UTF-8.  |
| `MISSING_HEADERS`          | Required columns are missing: {list}.                       |
| `EMPTY_FILE`               | The file contains no data rows.                             |
| `SERVER_ERROR`             | A server error occurred. Please try again in a few minutes. |
| `NETWORK_TIMEOUT`          | The upload timed out. Check your connection and try again.  |

---

## Counts Display Rules

### Terminology

| Term        | Definition                                       | When to Show |
| ----------- | ------------------------------------------------ | ------------ |
| **Created** | New record inserted                              | Always       |
| **Matched** | Existing record found via dedupe key; no insert  | When > 0     |
| **Skipped** | Row intentionally not processed (e.g., filtered) | When > 0     |
| **Failed**  | Row could not be processed due to error          | When > 0     |

### Display Priority

1. **Created** counts are always prominent (large stat cards)
2. **Matched** shown as supportive text below cards
3. **Failed** shown as red stat card only when > 0
4. **Skipped** shown as footnote only when > 0

### Example Counts Block (Processing/Complete)

```
┌──────────────────────────────────────────────────────────────┐
│                                                              │
│    PLAINTIFFS              JUDGMENTS                         │
│    ┌──────────────┐        ┌──────────────┐                  │
│    │     142      │        │     312      │                  │
│    │   created    │        │   created    │                  │
│    └──────────────┘        └──────────────┘                  │
│                                                              │
│    +89 matched existing    +47 matched existing              │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

---

## Retry Semantics & Idempotency

### Dedupe Detection Flow

```
1. Client computes SHA-256 hash of file contents
2. Client sends hash to POST /api/intake/check-duplicate
3. Server checks batch_imports.file_hash
4. If match found:
   - Return { duplicate: true, batch_id, batch_name, created_at }
   - UI transitions to DUPLICATE state
5. If no match:
   - Return { duplicate: false }
   - UI proceeds to UPLOADING
```

### API Contract

```typescript
// Check for duplicate
POST /api/intake/check-duplicate
Request:  { file_hash: string, file_name: string }
Response: {
  duplicate: boolean,
  batch_id?: string,
  batch_name?: string,
  created_at?: string,
  stats?: { plaintiffs_created: number, judgments_created: number }
}

// Upload with optional force flag
POST /api/intake/upload
Request:  FormData { file: File, force?: boolean }
Response: { batch_id: string, batch_name: string }

// Get batch status (for SSE fallback)
GET /api/intake/batch/{batch_id}/status
Response: {
  state: 'processing' | 'completed' | 'partial' | 'failed',
  rows_total: number,
  rows_processed: number,
  plaintiffs_created: number,
  plaintiffs_matched: number,
  judgments_created: number,
  judgments_matched: number,
  errors: Array<{ row: number, field: string, message: string }>,
  error_report_url?: string
}
```

### Idempotency Messages

| Scenario                          | Message                                                        |
| --------------------------------- | -------------------------------------------------------------- |
| Exact file match, batch completed | `This file was already uploaded`                               |
| Exact file match, batch partial   | `This file was already uploaded with {n} errors`               |
| Exact file match, batch failed    | `This file was previously uploaded but failed. You can retry.` |
| Same file name, different hash    | (No message; treat as new file)                                |

---

## Accessibility Requirements

1. **Keyboard Navigation:** All interactive elements focusable via Tab
2. **Screen Reader:** Announce state changes with `aria-live="polite"`
3. **Progress:** Use `role="progressbar"` with `aria-valuenow`
4. **Errors:** Associate error messages with `aria-describedby`
5. **Color:** Never rely on color alone (icons + text for states)

---

## Component Hierarchy

```
<IntakeStation>
  <Header title="Intake Station" />
  <DropZone
    state={state}
    onFileSelect={handleFile}
    onCancel={handleCancel}
  />
  {state === 'duplicate' && (
    <DuplicateWarning
      batch={existingBatch}
      onViewBatch={navigateToBatch}
      onForceUpload={handleForceUpload}
    />
  )}
  {state === 'processing' && (
    <ProcessingProgress counts={counts} batchId={batchId} />
  )}
  {state === 'completed' && (
    <CompletedSummary counts={counts} batchId={batchId} />
  )}
  {state === 'partial' && (
    <PartialSummary
      counts={counts}
      errors={topErrors}
      errorReportUrl={errorReportUrl}
      batchId={batchId}
    />
  )}
  {state === 'failed' && (
    <FailedMessage error={error} batchId={batchId} onRetry={reset} />
  )}
  <RecentBatches batches={recentBatches} />
</IntakeStation>
```

---

## State Transitions Summary

| From       | Event             | To              |
| ---------- | ----------------- | --------------- |
| IDLE       | File selected     | VALIDATING      |
| VALIDATING | Invalid file      | FAILED          |
| VALIDATING | Valid + duplicate | DUPLICATE       |
| VALIDATING | Valid + new       | UPLOADING       |
| DUPLICATE  | View Batch        | (navigate away) |
| DUPLICATE  | Force Upload      | UPLOADING       |
| UPLOADING  | Cancel clicked    | IDLE            |
| UPLOADING  | Network error     | FAILED          |
| UPLOADING  | Upload complete   | PROCESSING      |
| PROCESSING | All rows OK       | COMPLETED       |
| PROCESSING | Some rows fail    | PARTIAL         |
| PROCESSING | Fatal error       | FAILED          |
| COMPLETED  | Upload Another    | IDLE            |
| PARTIAL    | Upload Another    | IDLE            |
| FAILED     | Try Again         | IDLE            |

---

## Implementation Checklist

- [ ] Implement SHA-256 hashing in browser (Web Crypto API)
- [ ] Create `/api/intake/check-duplicate` endpoint
- [ ] Create `/api/intake/upload` endpoint with `force` param
- [ ] Create `/api/intake/batch/{id}/status` SSE endpoint
- [ ] Store `file_hash` in `batch_imports` table
- [ ] Generate error report CSV and store in `data_error/`
- [ ] Implement all 8 UI states with transitions
- [ ] Add Recent Batches query (last 10, sorted by date)
- [ ] Add aria-live announcements for state changes
- [ ] Add download link for error report CSV
