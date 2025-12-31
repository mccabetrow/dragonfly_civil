# Dragonfly Civil - Data Contract Specification

**Version:** 1.0.0  
**Last Updated:** 2025-01-04  
**Owner:** Staff Engineering  
**Status:** Production

---

## Table of Contents

1. [Overview](#overview)
2. [CSV Schema: Judgments](#csv-schema-judgments)
3. [CSV Schema: Plaintiffs](#csv-schema-plaintiffs)
4. [Normalization Rules](#normalization-rules)
5. [Validation Rules & Error Codes](#validation-rules--error-codes)
6. [Deduplication Strategy](#deduplication-strategy)
7. [Error Budget Policy](#error-budget-policy)
8. [API Response Contract](#api-response-contract)
9. [Acceptance Criteria](#acceptance-criteria)
10. [Edge Cases & Failure Modes](#edge-cases--failure-modes)

---

## Overview

This document defines the canonical data contract for the Dragonfly Civil ingestion pipeline. All CSV imports, validations, and API responses MUST conform to this specification.

### Design Principles

1. **Idempotency**: Same input always produces same output (file_hash deduplication)
2. **Fail-Fast**: Validate ALL rows before ANY inserts
3. **Error Budget**: Reject entire batch if error rate exceeds threshold
4. **Observability**: Every validation error generates machine-readable error code
5. **Normalization**: Consistent transforms for names, amounts, dates, case numbers

---

## CSV Schema: Judgments

### Source: Simplicity Export (Primary)

#### Column Mapping

| CSV Column   | DB Column        | Type          | Required | Notes                       |
| ------------ | ---------------- | ------------- | -------- | --------------------------- |
| `File #`     | `case_number`    | TEXT          | ✅ Yes   | Case identifier, normalized |
| `Plaintiff`  | `plaintiff_name` | TEXT          | ✅ Yes   | Creditor/claimant name      |
| `Defendant`  | `defendant_name` | TEXT          | ✅ Yes   | Debtor/respondent name      |
| `Amount`     | `amount`         | NUMERIC(12,2) | ✅ Yes   | Judgment amount in USD      |
| `Entry Date` | `filed_date`     | DATE          | ✅ Yes   | Date judgment entered       |
| `Court`      | `court`          | TEXT          | ❌ No    | Court name (normalized)     |
| `County`     | `county`         | TEXT          | ❌ No    | County name (normalized)    |

#### Example Valid Row

```csv
File #,Plaintiff,Defendant,Amount,Entry Date,Court,County
2024-CV-12345,Acme Collections LLC,John Q. Public,"$12,500.00",01/15/2024,New York Supreme Court,New York
```

#### Canonical Schema (Database)

```sql
CREATE TABLE public.judgments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_number TEXT NOT NULL UNIQUE,  -- Dedupe key
    plaintiff_name TEXT NOT NULL,
    defendant_name TEXT NOT NULL,
    amount NUMERIC(12,2) NOT NULL CHECK (amount >= 0),
    filed_date DATE NOT NULL,
    court TEXT,
    county TEXT,
    source TEXT NOT NULL DEFAULT 'simplicity',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Normalization artifacts
    case_number_normalized TEXT GENERATED ALWAYS AS (
        REGEXP_REPLACE(UPPER(TRIM(case_number)), '[^A-Z0-9]', '', 'g')
    ) STORED,
    plaintiff_name_normalized TEXT GENERATED ALWAYS AS (
        UPPER(TRIM(REGEXP_REPLACE(plaintiff_name, '\s+', ' ', 'g')))
    ) STORED,
    defendant_name_normalized TEXT GENERATED ALWAYS AS (
        UPPER(TRIM(REGEXP_REPLACE(defendant_name, '\s+', ' ', 'g')))
    ) STORED
);

CREATE INDEX idx_judgments_case_number_normalized ON public.judgments(case_number_normalized);
CREATE INDEX idx_judgments_filed_date ON public.judgments(filed_date);
CREATE INDEX idx_judgments_amount ON public.judgments(amount DESC);
```

---

## CSV Schema: Plaintiffs

### Source: Vendor Exports (Simplicity, JBI, etc.)

#### Column Mapping

| CSV Column       | DB Column       | Type | Required | Notes                           |
| ---------------- | --------------- | ---- | -------- | ------------------------------- |
| `File #`         | `case_number`   | TEXT | ✅ Yes   | Links to judgment               |
| `Plaintiff`      | `name`          | TEXT | ✅ Yes   | Legal name                      |
| `Address`        | `address_line1` | TEXT | ❌ No    | Street address                  |
| `City`           | `city`          | TEXT | ❌ No    | City name                       |
| `State`          | `state`         | TEXT | ❌ No    | 2-letter state code             |
| `ZIP`            | `zip`           | TEXT | ❌ No    | 5 or 9-digit ZIP                |
| `Phone`          | `phone`         | TEXT | ❌ No    | Normalized to E.164             |
| `Email`          | `email`         | TEXT | ❌ No    | Lowercased, validated           |
| `Contact Person` | `contact_name`  | TEXT | ❌ No    | Primary contact                 |
| `Status`         | `status`        | TEXT | ❌ No    | Current status (mapped to enum) |

#### Example Valid Row

```csv
File #,Plaintiff,Address,City,State,ZIP,Phone,Email,Contact Person,Status
2024-CV-12345,Acme Collections LLC,123 Main St,New York,NY,10001,(212) 555-1234,billing@acme.com,Jane Smith,Active
```

#### Canonical Schema (Database)

```sql
CREATE TABLE public.plaintiffs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    address_line1 TEXT,
    address_line2 TEXT,
    city TEXT,
    state TEXT,
    zip TEXT,
    phone TEXT,  -- Stored as E.164: +12125551234
    email TEXT,  -- Lowercased, validated
    contact_name TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    source TEXT NOT NULL,
    source_reference TEXT,  -- Vendor batch ID
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Normalization artifacts
    name_normalized TEXT GENERATED ALWAYS AS (
        UPPER(TRIM(REGEXP_REPLACE(name, '\s+', ' ', 'g')))
    ) STORED,
    email_normalized TEXT GENERATED ALWAYS AS (
        LOWER(TRIM(email))
    ) STORED,
    -- Dedupe key (name + address)
    dedupe_key TEXT GENERATED ALWAYS AS (
        MD5(
            COALESCE(UPPER(TRIM(name)), '') || '|' ||
            COALESCE(UPPER(TRIM(address_line1)), '') || '|' ||
            COALESCE(UPPER(TRIM(zip)), '')
        )
    ) STORED
);

CREATE UNIQUE INDEX idx_plaintiffs_dedupe_key ON public.plaintiffs(dedupe_key);
CREATE INDEX idx_plaintiffs_name_normalized ON public.plaintiffs USING gin(name_normalized gin_trgm_ops);
CREATE INDEX idx_plaintiffs_status ON public.plaintiffs(status);
```

---

## Normalization Rules

### 1. Names (Person & Organization)

#### Rules

- Trim leading/trailing whitespace
- Collapse multiple spaces to single space
- Uppercase for comparison (stored as-is for display)
- Remove common suffixes for deduplication: `LLC`, `INC`, `CORP`, `LTD`, `CO`
- Normalize legal entity indicators: `L.L.C.` → `LLC`, `Inc.` → `INC`

#### Python Implementation

```python
import re
from typing import Optional

def normalize_name(name: str) -> str:
    """Normalize name for deduplication."""
    # Trim and collapse spaces
    normalized = re.sub(r'\s+', ' ', name.strip())

    # Uppercase for comparison
    normalized = normalized.upper()

    # Remove punctuation except hyphens in names
    normalized = re.sub(r'[^\w\s\-]', '', normalized)

    # Normalize legal entity indicators
    entity_patterns = [
        (r'\bL\.L\.C\.\s*$', 'LLC'),
        (r'\bINC\.\s*$', 'INC'),
        (r'\bCORP\.\s*$', 'CORP'),
        (r'\bCO\.\s*$', 'CO'),
    ]
    for pattern, replacement in entity_patterns:
        normalized = re.sub(pattern, replacement, normalized)

    return normalized

# Examples
assert normalize_name("Acme   Collections,  LLC") == "ACME COLLECTIONS LLC"
assert normalize_name("John Q. Public") == "JOHN Q PUBLIC"
assert normalize_name("Smith & Associates, Inc.") == "SMITH  ASSOCIATES INC"
```

### 2. Amounts (Currency)

#### Rules

- Remove currency symbols: `$`, `USD`
- Remove grouping separators: `,`
- Parse as Decimal(12, 2) for precision
- Reject negative amounts (error code: `INVALID_AMOUNT_NEGATIVE`)
- Reject amounts > $999,999,999.99 (error code: `INVALID_AMOUNT_TOO_LARGE`)

#### Python Implementation

```python
from decimal import Decimal, InvalidOperation

def normalize_amount(amount: str) -> Decimal:
    """Normalize currency amount to Decimal."""
    # Remove currency symbols and whitespace
    normalized = amount.strip().upper()
    normalized = normalized.replace('$', '').replace('USD', '').replace(',', '')

    try:
        decimal_amount = Decimal(normalized)
    except InvalidOperation:
        raise ValueError(f"INVALID_AMOUNT_FORMAT: {amount}")

    # Validate range
    if decimal_amount < 0:
        raise ValueError(f"INVALID_AMOUNT_NEGATIVE: {amount}")

    if decimal_amount > Decimal('999999999.99'):
        raise ValueError(f"INVALID_AMOUNT_TOO_LARGE: {amount}")

    # Round to 2 decimal places
    return decimal_amount.quantize(Decimal('0.01'))

# Examples
assert normalize_amount("$12,500.00") == Decimal("12500.00")
assert normalize_amount("1234.567") == Decimal("1234.57")  # Rounds
assert normalize_amount("USD 999.99") == Decimal("999.99")
```

### 3. Case Numbers

#### Rules

- Trim whitespace
- Uppercase for comparison
- Remove non-alphanumeric characters (except hyphens)
- Normalize common patterns: `CV-12345` ≈ `CV12345` ≈ `cv 12345`

#### Python Implementation

```python
def normalize_case_number(case_number: str) -> str:
    """Normalize case number for deduplication."""
    # Remove all non-alphanumeric except hyphens
    normalized = re.sub(r'[^A-Z0-9\-]', '', case_number.strip().upper())
    return normalized

# Examples
assert normalize_case_number("2024-CV-12345") == "2024-CV-12345"
assert normalize_case_number("cv 12345") == "CV12345"
assert normalize_case_number("CV#12345") == "CV12345"
```

### 4. Counties & Courts

#### Rules

- Trim whitespace
- Title case for display
- Normalize common abbreviations:
  - `Co.` → `County`
  - `Ct.` → `Court`
  - `Sup. Ct.` → `Supreme Court`
  - `Dist. Ct.` → `District Court`

#### Python Implementation

```python
def normalize_location(location: str) -> str:
    """Normalize county/court name."""
    if not location:
        return ""

    # Trim and title case
    normalized = location.strip().title()

    # Expand abbreviations
    expansions = [
        (r'\bCo\.\s*$', 'County'),
        (r'\bCt\.\s*$', 'Court'),
        (r'\bSup\. Ct\.\s*$', 'Supreme Court'),
        (r'\bDist\. Ct\.\s*$', 'District Court'),
    ]
    for pattern, replacement in expansions:
        normalized = re.sub(pattern, replacement, normalized)

    return normalized

# Examples
assert normalize_location("NEW YORK CO.") == "New York County"
assert normalize_location("SUP. CT.") == "Supreme Court"
```

### 5. Dates

#### Rules

- Accept formats: `MM/DD/YYYY`, `YYYY-MM-DD`, `DD-MMM-YYYY`
- Reject future dates (error code: `INVALID_DATE_FUTURE`)
- Reject dates before 1900 (error code: `INVALID_DATE_TOO_OLD`)
- Store as `DATE` type (no time component)

#### Python Implementation

```python
from datetime import datetime, date

def normalize_date(date_str: str) -> date:
    """Parse and validate date."""
    # Try common formats
    formats = [
        '%m/%d/%Y',      # 01/15/2024
        '%Y-%m-%d',      # 2024-01-15
        '%d-%b-%Y',      # 15-JAN-2024
        '%m-%d-%Y',      # 01-15-2024
    ]

    parsed_date = None
    for fmt in formats:
        try:
            parsed_date = datetime.strptime(date_str.strip(), fmt).date()
            break
        except ValueError:
            continue

    if not parsed_date:
        raise ValueError(f"INVALID_DATE_FORMAT: {date_str}")

    # Validate range
    if parsed_date > date.today():
        raise ValueError(f"INVALID_DATE_FUTURE: {date_str}")

    if parsed_date.year < 1900:
        raise ValueError(f"INVALID_DATE_TOO_OLD: {date_str}")

    return parsed_date

# Examples
assert normalize_date("01/15/2024") == date(2024, 1, 15)
assert normalize_date("2024-01-15") == date(2024, 1, 15)
```

---

## Validation Rules & Error Codes

### Error Code Format

`<ENTITY>_<FIELD>_<REASON>`

- **ENTITY**: `JUDGMENT`, `PLAINTIFF`, `BATCH`
- **FIELD**: Column name (snake_case)
- **REASON**: Short descriptor (uppercase)

### Validation Rules Matrix

| Field            | Validation           | Error Code                      | Severity |
| ---------------- | -------------------- | ------------------------------- | -------- |
| `case_number`    | Required, not empty  | `JUDGMENT_CASE_NUMBER_MISSING`  | CRITICAL |
| `case_number`    | Max length 100       | `JUDGMENT_CASE_NUMBER_TOO_LONG` | CRITICAL |
| `plaintiff_name` | Required, not empty  | `JUDGMENT_PLAINTIFF_MISSING`    | CRITICAL |
| `plaintiff_name` | Max length 500       | `JUDGMENT_PLAINTIFF_TOO_LONG`   | WARNING  |
| `defendant_name` | Required, not empty  | `JUDGMENT_DEFENDANT_MISSING`    | CRITICAL |
| `defendant_name` | Max length 500       | `JUDGMENT_DEFENDANT_TOO_LONG`   | WARNING  |
| `amount`         | Required, numeric    | `JUDGMENT_AMOUNT_INVALID`       | CRITICAL |
| `amount`         | Amount >= 0          | `JUDGMENT_AMOUNT_NEGATIVE`      | CRITICAL |
| `amount`         | Amount < $1B         | `JUDGMENT_AMOUNT_TOO_LARGE`     | WARNING  |
| `filed_date`     | Required, valid date | `JUDGMENT_FILED_DATE_INVALID`   | CRITICAL |
| `filed_date`     | Date not in future   | `JUDGMENT_FILED_DATE_FUTURE`    | CRITICAL |
| `filed_date`     | Date >= 1900-01-01   | `JUDGMENT_FILED_DATE_TOO_OLD`   | WARNING  |
| `court`          | Max length 200       | `JUDGMENT_COURT_TOO_LONG`       | WARNING  |
| `county`         | Max length 100       | `JUDGMENT_COUNTY_TOO_LONG`      | WARNING  |

### Row-Level Error Structure

Stored in `intake.row_errors`:

```sql
CREATE TABLE intake.row_errors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id UUID NOT NULL REFERENCES intake.simplicity_batches(id) ON DELETE CASCADE,
    row_number INTEGER NOT NULL,
    error_code TEXT NOT NULL,
    error_message TEXT NOT NULL,
    raw_data JSONB,  -- Original CSV row for debugging
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_row_errors_batch_id ON intake.row_errors(batch_id);
CREATE INDEX idx_row_errors_error_code ON intake.row_errors(error_code);
```

### Example Error Record

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "batch_id": "123e4567-e89b-12d3-a456-426614174000",
  "row_number": 42,
  "error_code": "JUDGMENT_AMOUNT_INVALID",
  "error_message": "Amount 'NOT_A_NUMBER' cannot be parsed as numeric",
  "raw_data": {
    "File #": "2024-CV-12345",
    "Plaintiff": "Acme LLC",
    "Defendant": "John Doe",
    "Amount": "NOT_A_NUMBER",
    "Entry Date": "01/15/2024",
    "Court": "NY Supreme Court",
    "County": "New York"
  },
  "created_at": "2025-01-04T15:30:00Z"
}
```

---

## Deduplication Strategy

### Judgments Dedupe Key

**Primary Key:** `case_number` (normalized)

**Collision Risk:** Medium

- Same case number from different courts (low probability)
- Typos in vendor data (`CV-12345` vs `CV-12346`)

**Collision Handling:**

1. **Idempotency Check**: File hash at upload time (prevents re-processing same export)
2. **Unique Constraint**: `judgments(case_number)` UNIQUE constraint (rejects duplicates)
3. **Upsert Logic**: For amended judgments, use `ON CONFLICT (case_number) DO UPDATE`

#### Amended Judgment Handling

```sql
-- Upsert pattern for amended judgments (amount changes, date corrections)
INSERT INTO public.judgments (
    case_number, plaintiff_name, defendant_name, amount, filed_date, court, county, source
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8
)
ON CONFLICT (case_number) DO UPDATE SET
    amount = EXCLUDED.amount,              -- Update amount if amended
    filed_date = EXCLUDED.filed_date,      -- Update date if corrected
    plaintiff_name = EXCLUDED.plaintiff_name,
    defendant_name = EXCLUDED.defendant_name,
    court = EXCLUDED.court,
    county = EXCLUDED.county,
    updated_at = NOW()
WHERE
    -- Only update if values actually changed
    judgments.amount IS DISTINCT FROM EXCLUDED.amount OR
    judgments.filed_date IS DISTINCT FROM EXCLUDED.filed_date OR
    judgments.plaintiff_name IS DISTINCT FROM EXCLUDED.plaintiff_name OR
    judgments.defendant_name IS DISTINCT FROM EXCLUDED.defendant_name;
```

### Plaintiffs Dedupe Key

**Composite Key:** `MD5(name + address_line1 + zip)` (normalized)

**Collision Risk:** High

- Same plaintiff at multiple locations (branches)
- Name variations (`Acme LLC` vs `Acme Collections LLC`)
- Address typos

**Collision Handling:**

1. **Fuzzy Matching**: Use `pg_trgm` for trigram similarity on `name_normalized`
2. **Manual Review Queue**: Store potential duplicates in `public.plaintiff_duplicates`
3. **Confidence Scoring**: Levenshtein distance + address match + phone match

#### Duplicate Detection Query

```sql
-- Find potential plaintiff duplicates (>80% name similarity)
SELECT
    p1.id AS id_a,
    p2.id AS id_b,
    p1.name AS name_a,
    p2.name AS name_b,
    SIMILARITY(p1.name_normalized, p2.name_normalized) AS name_similarity,
    (p1.phone = p2.phone) AS phone_match,
    (p1.zip = p2.zip) AS zip_match
FROM public.plaintiffs p1
CROSS JOIN public.plaintiffs p2
WHERE
    p1.id < p2.id  -- Avoid self-comparison and duplicate pairs
    AND SIMILARITY(p1.name_normalized, p2.name_normalized) > 0.8
ORDER BY name_similarity DESC;
```

### Batch-Level Deduplication

**File Hash:** SHA-256 of entire CSV file content

**Idempotency Guarantee:**

- `intake.simplicity_batches(file_hash)` UNIQUE constraint
- Upload endpoint checks file_hash BEFORE creating batch record
- If duplicate detected, return existing batch_id (no new processing)

```python
import hashlib

def compute_file_hash(file_content: bytes) -> str:
    """Compute SHA-256 hash for file deduplication."""
    return hashlib.sha256(file_content).hexdigest()
```

---

## Error Budget Policy

### Definition

**Error Budget:** Maximum percentage of invalid rows allowed in a batch before rejection.

**Default:** 10% (configurable per batch via `error_threshold_percent` column)

### Policy Rules

1. **Pre-Insert Validation**: ALL rows validated BEFORE ANY inserts
2. **Budget Check**: Calculate `error_rate = (invalid_count / total_count) * 100`
3. **Rejection**: If `error_rate > error_threshold_percent`, reject entire batch
4. **Partial Success**: If within budget, insert valid rows only, log invalid rows in `intake.row_errors`

### Two-Phase Processing

```python
from dataclasses import dataclass
from typing import List

@dataclass
class ValidationResult:
    valid_rows: List[dict]
    invalid_rows: List[dict]
    error_rate: float

def process_batch(rows: List[dict], error_threshold_percent: float = 10.0) -> ValidationResult:
    """Two-phase batch processing with error budget."""
    valid_rows = []
    invalid_rows = []

    # PHASE 1: Validate ALL rows
    for row in rows:
        try:
            validated_row = validate_row(row)
            valid_rows.append(validated_row)
        except ValidationError as e:
            invalid_rows.append({
                'row': row,
                'error': str(e)
            })

    # Calculate error rate
    total_count = len(rows)
    invalid_count = len(invalid_rows)
    error_rate = (invalid_count / total_count * 100) if total_count > 0 else 0.0

    # PHASE 2: Check error budget BEFORE any inserts
    if error_rate > error_threshold_percent:
        raise ErrorBudgetExceeded(
            f"Error rate {error_rate:.1f}% exceeds limit {error_threshold_percent}%"
        )

    # PHASE 3: Insert valid rows only (if budget OK)
    insert_rows(valid_rows)

    return ValidationResult(
        valid_rows=valid_rows,
        invalid_rows=invalid_rows,
        error_rate=error_rate
    )
```

### Batch Status Transitions

```
uploaded → validating → [budget check]
                            ↓
        [PASS]                              [FAIL]
          ↓                                   ↓
      inserting                           failed
          ↓                           (rejection_reason set)
      completed
```

### Status Definitions

| Status       | Description                                             | Terminal |
| ------------ | ------------------------------------------------------- | -------- |
| `uploaded`   | CSV uploaded, pending processing                        | No       |
| `staging`    | File staged in storage                                  | No       |
| `validating` | Rows being validated                                    | No       |
| `inserting`  | Rows being inserted (budget passed)                     | No       |
| `completed`  | All valid rows inserted successfully                    | Yes      |
| `failed`     | Error budget exceeded OR critical processing error      | Yes      |
| `partial`    | Some rows inserted (deprecated - use row_count metrics) | Yes      |

---

## API Response Contract

### Endpoint: `GET /intake/batches/{batch_id}`

#### Response Schema (JSON)

```typescript
interface BatchStatusResult {
  // Identifiers
  id: string; // UUID
  filename: string; // Original CSV filename
  fileHash: string; // SHA-256 hash (hex)

  // Status
  status: BatchStatus; // uploaded | validating | inserting | completed | failed

  // Row Counts
  rowCountTotal: number; // Total rows in CSV (excludes header)
  rowCountInserted: number; // Successfully inserted rows
  rowCountInvalid: number; // Failed validation rows
  rowCountDuplicate: number; // Duplicate case_number rows

  // Error Budget
  errorThresholdPercent: number; // Error budget threshold (default 10)
  errorRate: number; // Calculated: (invalid / total) * 100
  rejectionReason: string | null; // Populated if status=failed

  // Timing Metrics
  parseDurationMs: number | null; // CSV parse time (milliseconds)
  dbDurationMs: number | null; // DB insert time (milliseconds)
  throughputRowsPerSec: number; // Calculated: total / (parse + db) * 1000

  // Timestamps
  createdAt: string; // ISO 8601: 2025-01-04T15:30:00Z
  completedAt: string | null; // ISO 8601 or null if not completed

  // Metadata
  source: string; // simplicity | jbi | manual
  sourceReference: string | null; // Vendor batch ID
}

type BatchStatus =
  | "uploaded"
  | "staging"
  | "validating"
  | "transforming"
  | "inserting"
  | "upserting"
  | "processing" // Generic processing state
  | "completed"
  | "failed"
  | "partial"; // Deprecated
```

#### Example Response (Success)

```json
{
  "id": "123e4567-e89b-12d3-a456-426614174000",
  "filename": "simplicity_export_2025-01-04.csv",
  "fileHash": "d6cc61da42739ac2434e7b809cc21b92acb8a47110dcacf23a5bca27cea4dadc",
  "status": "completed",
  "rowCountTotal": 5000,
  "rowCountInserted": 4950,
  "rowCountInvalid": 50,
  "rowCountDuplicate": 0,
  "errorThresholdPercent": 10.0,
  "errorRate": 1.0,
  "rejectionReason": null,
  "parseDurationMs": 1250,
  "dbDurationMs": 3800,
  "throughputRowsPerSec": 990.0,
  "createdAt": "2025-01-04T15:30:00Z",
  "completedAt": "2025-01-04T15:30:05Z",
  "source": "simplicity",
  "sourceReference": "batch-2025-01-04-001"
}
```

#### Example Response (Failed - Error Budget)

```json
{
  "id": "123e4567-e89b-12d3-a456-426614174001",
  "filename": "bad_export_2025-01-04.csv",
  "fileHash": "7d9fa76b40857cece6d26f593165d884c82aba929af5de6950a8fe00c25839b3",
  "status": "failed",
  "rowCountTotal": 100,
  "rowCountInserted": 0,
  "rowCountInvalid": 85,
  "rowCountDuplicate": 0,
  "errorThresholdPercent": 10.0,
  "errorRate": 85.0,
  "rejectionReason": "Error rate 85.0% exceeded limit 10.0% (85/100 rows invalid)",
  "parseDurationMs": 450,
  "dbDurationMs": null,
  "throughputRowsPerSec": 0,
  "createdAt": "2025-01-04T15:45:00Z",
  "completedAt": "2025-01-04T15:45:01Z",
  "source": "simplicity",
  "sourceReference": null
}
```

### Endpoint: `GET /intake/batches/{batch_id}/errors`

#### Response Schema (JSON)

```typescript
interface BatchErrorsResult {
  batchId: string;
  totalErrors: number;
  errors: Array<{
    rowNumber: number;
    errorCode: string;
    errorMessage: string;
    rawData: Record<string, string>; // Original CSV row
  }>;
}
```

#### Example Response

```json
{
  "batchId": "123e4567-e89b-12d3-a456-426614174000",
  "totalErrors": 50,
  "errors": [
    {
      "rowNumber": 42,
      "errorCode": "JUDGMENT_AMOUNT_INVALID",
      "errorMessage": "Amount 'NOT_A_NUMBER' cannot be parsed as numeric",
      "rawData": {
        "File #": "2024-CV-12345",
        "Plaintiff": "Acme LLC",
        "Defendant": "John Doe",
        "Amount": "NOT_A_NUMBER",
        "Entry Date": "01/15/2024",
        "Court": "NY Supreme Court",
        "County": "New York"
      }
    },
    {
      "rowNumber": 85,
      "errorCode": "JUDGMENT_DEFENDANT_MISSING",
      "errorMessage": "Defendant name is required but was empty",
      "rawData": {
        "File #": "2024-CV-67890",
        "Plaintiff": "Test Plaintiff",
        "Defendant": "",
        "Amount": "$1,000.00",
        "Entry Date": "02/01/2024",
        "Court": "NY Supreme Court",
        "County": "New York"
      }
    }
  ]
}
```

### Database-to-API Mapping (Snake → Camel)

```python
def map_batch_to_api(batch: dict) -> dict:
    """Map database row to API response."""
    return {
        'id': batch['id'],
        'filename': batch['filename'],
        'fileHash': batch['file_hash'],
        'status': batch['status'],
        'rowCountTotal': batch['row_count_total'],
        'rowCountInserted': batch['row_count_inserted'],
        'rowCountInvalid': batch['row_count_invalid'],
        'rowCountDuplicate': batch['row_count_duplicate'],
        'errorThresholdPercent': batch['error_threshold_percent'],
        'errorRate': (
            (batch['row_count_invalid'] / batch['row_count_total'] * 100)
            if batch['row_count_total'] > 0 else 0.0
        ),
        'rejectionReason': batch['rejection_reason'],
        'parseDurationMs': batch['parse_duration_ms'],
        'dbDurationMs': batch['db_duration_ms'],
        'throughputRowsPerSec': calculate_throughput(batch),
        'createdAt': batch['created_at'].isoformat(),
        'completedAt': batch['completed_at'].isoformat() if batch['completed_at'] else None,
        'source': batch['source'],
        'sourceReference': batch['source_reference'],
    }

def calculate_throughput(batch: dict) -> float:
    """Calculate rows per second throughput."""
    total_ms = (batch['parse_duration_ms'] or 0) + (batch['db_duration_ms'] or 0)
    if total_ms == 0:
        return 0.0
    return batch['row_count_total'] / (total_ms / 1000.0)
```

---

## Acceptance Criteria

### Functional Requirements

1. **Idempotency**

   - ✅ Same CSV uploaded twice returns same batch_id
   - ✅ No duplicate inserts (file_hash UNIQUE)
   - ✅ No duplicate judgments (case_number UNIQUE)

2. **Validation**

   - ✅ All required fields validated
   - ✅ Machine-readable error codes generated
   - ✅ Invalid rows stored in `intake.row_errors`

3. **Error Budget**

   - ✅ Batch rejected if error rate > threshold
   - ✅ No partial inserts on rejection (all-or-nothing)
   - ✅ Rejection reason populated in API response

4. **Normalization**

   - ✅ Names normalized (whitespace, case, entities)
   - ✅ Amounts parsed and validated ($0 to $1B)
   - ✅ Dates validated (not future, not pre-1900)
   - ✅ Case numbers normalized for deduplication

5. **Observability**
   - ✅ Timing metrics recorded (parse_ms, db_ms)
   - ✅ Throughput calculated (rows/sec)
   - ✅ Error distribution queryable via `ops.v_error_distribution`

### Non-Functional Requirements

1. **Performance**

   - ✅ Parse 10K rows in < 5 seconds
   - ✅ Insert 10K rows in < 15 seconds
   - ✅ API response time < 500ms (p95)

2. **Reliability**

   - ✅ Transactional integrity (ACID guarantees)
   - ✅ Graceful failure (no orphaned data)
   - ✅ Retry-safe (idempotent operations)

3. **Maintainability**
   - ✅ Error codes documented
   - ✅ Normalization rules testable
   - ✅ API contract versioned

---

## Edge Cases & Failure Modes

### Edge Case Matrix

| Scenario                                | Expected Behavior                                     | Error Code / Status                                  |
| --------------------------------------- | ----------------------------------------------------- | ---------------------------------------------------- | -------------- |
| Empty CSV (header only)                 | Reject with error                                     | `BATCH_EMPTY_FILE`                                   |
| Missing required column                 | Reject entire batch                                   | `BATCH_MISSING_COLUMN`                               |
| Extra columns (not in schema)           | Ignore extra columns, process valid ones              | N/A (warning logged)                                 |
| Column order changed                    | Process correctly (match by header name)              | N/A                                                  |
| UTF-8 BOM marker                        | Strip BOM, process normally                           | N/A                                                  |
| Non-UTF-8 encoding (Latin-1, etc.)      | Attempt decode with fallback, log warning             | `BATCH_ENCODING_WARNING`                             |
| Case number with leading zeros          | Preserve as-is (`00123` ≠ `123`)                      | N/A                                                  |
| Case number collision (duplicate)       | Skip duplicate, increment `row_count_duplicate`       | `JUDGMENT_DUPLICATE`                                 |
| Amount with multiple decimals (`1.2.3`) | Validation error                                      | `JUDGMENT_AMOUNT_INVALID`                            |
| Date in future                          | Validation error                                      | `JUDGMENT_FILED_DATE_FUTURE`                         |
| Negative amount (`-$100`)               | Validation error                                      | `JUDGMENT_AMOUNT_NEGATIVE`                           |
| Plaintiff name = Defendant name         | Allow (legal self-debt scenarios exist)               | N/A (warning logged)                                 |
| Very long names (> 500 chars)           | Truncate with warning                                 | `JUDGMENT_NAME_TOO_LONG`                             |
| Special characters in names (`@#$%`)    | Allow (some legal entities use special chars)         | N/A                                                  |
| NULL values in optional fields          | Store as NULL in database                             | N/A                                                  |
| Empty string in optional fields         | Convert to NULL (normalize empties)                   | N/A                                                  |
| All rows invalid (100% error rate)      | Reject batch, status=failed                           | Error budget exceeded                                |
| Amended judgment (case_number exists)   | UPDATE existing row (upsert logic)                    | N/A                                                  |
| File hash collision (SHA-256 dupe)      | Return existing batch_id, no reprocessing             | N/A (idempotency)                                    |
| Concurrent uploads of same file         | One succeeds, others get existing batch_id            | N/A (idempotency)                                    |
| Worker crash mid-processing             | Batch remains in `validating` status (stuck)          | Sentinel detects, alerts                             |
| Database connection timeout             | Retry with exponential backoff, fail after 3 attempts | `BATCH_DB_TIMEOUT`                                   |
| Out-of-memory (10M+ rows)               | Process in chunks (10K rows per chunk)                | N/A                                                  |
| CSV injection attack (`=cmd             | '/c calc'`)                                           | Sanitize formulas, escape leading `=`, `+`, `-`, `@` | N/A (security) |

### Failure Mode Recovery

#### Stuck Batch Recovery

```sql
-- Manual intervention: reset stuck batch to uploaded state
UPDATE intake.simplicity_batches
SET status = 'uploaded', updated_at = NOW()
WHERE id = '<BATCH_ID>' AND status IN ('validating', 'inserting');
```

#### Orphaned Errors Cleanup

```sql
-- Remove errors for completed/failed batches older than 90 days
DELETE FROM intake.row_errors
WHERE batch_id IN (
    SELECT id FROM intake.simplicity_batches
    WHERE status IN ('completed', 'failed')
    AND completed_at < NOW() - INTERVAL '90 days'
);
```

#### Data Integrity Check

```sql
-- Verify no orphaned errors (batch_id FK should prevent this)
SELECT COUNT(*) FROM intake.row_errors re
LEFT JOIN intake.simplicity_batches sb ON re.batch_id = sb.id
WHERE sb.id IS NULL;
-- Expected: 0
```

---

## Versioning & Changes

### Version History

| Version | Date       | Author            | Changes                            |
| ------- | ---------- | ----------------- | ---------------------------------- |
| 1.0.0   | 2025-01-04 | Staff Engineering | Initial release (production-ready) |

### Breaking Changes

Any changes to this contract that affect existing API consumers or database schemas MUST:

1. Increment major version (e.g., 1.0.0 → 2.0.0)
2. Provide 30-day migration period
3. Update all documentation and tests
4. Run regression suite against prod data snapshot

### Non-Breaking Changes

- Adding optional fields (OK)
- Adding new error codes (OK)
- Improving normalization (OK if backward-compatible)
- Performance optimizations (OK)

---

## Appendix A: Error Code Reference

### Critical Errors (Block Ingestion)

| Error Code                     | Description                        | Field            |
| ------------------------------ | ---------------------------------- | ---------------- |
| `JUDGMENT_CASE_NUMBER_MISSING` | Case number is required            | `case_number`    |
| `JUDGMENT_PLAINTIFF_MISSING`   | Plaintiff name is required         | `plaintiff_name` |
| `JUDGMENT_DEFENDANT_MISSING`   | Defendant name is required         | `defendant_name` |
| `JUDGMENT_AMOUNT_INVALID`      | Amount cannot be parsed as numeric | `amount`         |
| `JUDGMENT_AMOUNT_NEGATIVE`     | Amount must be >= $0               | `amount`         |
| `JUDGMENT_FILED_DATE_INVALID`  | Date format not recognized         | `filed_date`     |
| `JUDGMENT_FILED_DATE_FUTURE`   | Date cannot be in the future       | `filed_date`     |
| `BATCH_MISSING_COLUMN`         | Required CSV column not found      | N/A              |
| `BATCH_EMPTY_FILE`             | CSV contains no data rows          | N/A              |

### Warning Errors (Logged, Not Blocking)

| Error Code                    | Description                                | Field            |
| ----------------------------- | ------------------------------------------ | ---------------- |
| `JUDGMENT_PLAINTIFF_TOO_LONG` | Plaintiff name truncated to 500 chars      | `plaintiff_name` |
| `JUDGMENT_DEFENDANT_TOO_LONG` | Defendant name truncated to 500 chars      | `defendant_name` |
| `JUDGMENT_AMOUNT_TOO_LARGE`   | Amount > $999M (possible data error)       | `amount`         |
| `JUDGMENT_FILED_DATE_TOO_OLD` | Date before 1900 (possible data error)     | `filed_date`     |
| `JUDGMENT_COURT_TOO_LONG`     | Court name truncated to 200 chars          | `court`          |
| `JUDGMENT_COUNTY_TOO_LONG`    | County name truncated to 100 chars         | `county`         |
| `BATCH_ENCODING_WARNING`      | Non-UTF-8 encoding detected, fallback used | N/A              |

---

## Appendix B: SQL Reference

### Create Batch

```sql
INSERT INTO intake.simplicity_batches (
    filename, file_hash, row_count_total, status, error_threshold_percent, source
) VALUES (
    $1, $2, $3, 'uploaded', 10.0, 'simplicity'
)
RETURNING id, created_at;
```

### Query Batch Status

```sql
SELECT
    id, filename, file_hash, status,
    row_count_total, row_count_inserted, row_count_invalid, row_count_duplicate,
    error_threshold_percent, rejection_reason,
    parse_duration_ms, db_duration_ms,
    created_at, completed_at, source, source_reference
FROM intake.simplicity_batches
WHERE id = $1;
```

### Insert Judgment (Upsert)

```sql
INSERT INTO public.judgments (
    case_number, plaintiff_name, defendant_name, amount, filed_date, court, county, source
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8
)
ON CONFLICT (case_number) DO UPDATE SET
    amount = EXCLUDED.amount,
    filed_date = EXCLUDED.filed_date,
    updated_at = NOW()
WHERE judgments.amount IS DISTINCT FROM EXCLUDED.amount
   OR judgments.filed_date IS DISTINCT FROM EXCLUDED.filed_date;
```

### Insert Row Error

```sql
INSERT INTO intake.row_errors (
    batch_id, row_number, error_code, error_message, raw_data
) VALUES (
    $1, $2, $3, $4, $5::jsonb
);
```

### Query Error Distribution

```sql
SELECT
    error_code,
    COUNT(*) AS occurrence_count,
    COUNT(DISTINCT batch_id) AS affected_batches,
    MAX(error_message) AS sample_message,
    MAX(created_at) AS last_seen_at
FROM intake.row_errors
WHERE created_at >= NOW() - INTERVAL '7 days'
GROUP BY error_code
ORDER BY occurrence_count DESC
LIMIT 20;
```

---

**END OF DATA CONTRACT SPECIFICATION v1.0.0**
