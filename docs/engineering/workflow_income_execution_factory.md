# Workflow: Income Execution Factory

> **File**: `n8n/flows/dragonfly_income_execution_factory_v1.json`  
> **Trigger**: Webhook from Streamlit dashboard with `judgment_id`  
> **Purpose**: Generate NY CPLR 5231 Income Execution documents, store in Supabase Storage, and notify Mom with mailing instructions.

---

## Overview

This workflow automates the generation of Income Execution (wage garnishment) documents under NY CPLR 5231. When triggered from the Streamlit dashboard, it:

1. Receives `judgment_id` via webhook.
2. Fetches the judgment and related `debtor_intelligence` from Supabase.
3. Validates preconditions (actionable status, employer info, income band).
4. Computes the current balance with 9% statutory interest.
5. Fills a pre-uploaded PDF template using `pdf-lib`.
6. Saves the generated PDF to Supabase Storage.
7. Inserts an `enforcement_actions` record with `action_type = 'income_execution'`.
8. Sends Mom an email with the PDF link and mailing checklist.

---

## Prerequisites

### Supabase Storage Setup

1. Create a storage bucket named `enforcement-documents`:

   ```sql
   INSERT INTO storage.buckets (id, name, public)
   VALUES ('enforcement-documents', 'enforcement-documents', false);
   ```

2. Upload the blank Income Execution PDF template to:

   ```
   enforcement-documents/templates/income_execution_template.pdf
   ```

3. Configure RLS policies for the bucket (service_role full access, authenticated read-only).

### PDF Template Fields

The Income Execution template should contain the following fillable form fields (AcroForm):

| Field Name          | Description                             |
| ------------------- | --------------------------------------- |
| `court_name`        | Name of the court that entered judgment |
| `case_index_number` | Court index/docket number               |
| `creditor_name`     | Original creditor (plaintiff)           |
| `debtor_name`       | Debtor (defendant) name                 |
| `judgment_date`     | Date judgment was entered               |
| `principal_amount`  | Original judgment amount                |
| `interest_amount`   | Accrued interest to date                |
| `total_balance`     | Principal + interest                    |
| `employer_name`     | Debtor's employer                       |
| `employer_address`  | Employer's address                      |
| `execution_date`    | Date of this execution                  |
| `county`            | County of judgment                      |

---

## Node-by-Node Breakdown

### 1. Webhook Trigger

**Node Type**: `n8n-nodes-base.webhook`  
**Name**: `Income Execution Webhook`

**Configuration**:

| Field          | Value                   |
| -------------- | ----------------------- |
| HTTP Method    | `POST`                  |
| Path           | `income-execution`      |
| Response Mode  | `Last Node`             |
| Authentication | `Header Auth` (API key) |

**Expected Request Body**:

```json
{
  "judgment_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "requested_by": "mom@dragonflycivil.com",
  "require_attorney_signature": true
}
```

**Output**:

```json
{
  "body": {
    "judgment_id": "a1b2c3d4-...",
    "requested_by": "mom@dragonflycivil.com",
    "require_attorney_signature": true
  }
}
```

---

### 2. Fetch Judgment

**Node Type**: `n8n-nodes-base.supabase`  
**Name**: `Fetch Judgment`

**Configuration**:

| Field     | Value                                      |
| --------- | ------------------------------------------ |
| Operation | `Select`                                   |
| Schema    | `public`                                   |
| Table     | `core_judgments`                           |
| Return    | `All matching rows`                        |
| Filters   | `id` equals `{{ $json.body.judgment_id }}` |

**Output** (example):

```json
{
  "id": "a1b2c3d4-...",
  "case_index_number": "2024-NY-12345",
  "debtor_name": "John Q. Debtor",
  "original_creditor": "Acme Collections LLC",
  "judgment_date": "2024-01-15",
  "principal_amount": 8500.0,
  "interest_rate": 9.0,
  "court_name": "Civil Court of the City of New York",
  "county": "Kings",
  "status": "unsatisfied",
  "collectability_score": 78,
  "created_at": "2024-11-30T14:00:00Z"
}
```

---

### 3. Fetch Debtor Intelligence

**Node Type**: `n8n-nodes-base.supabase`  
**Name**: `Fetch Debtor Intelligence`

**Configuration**:

| Field     | Value                                 |
| --------- | ------------------------------------- |
| Operation | `Select`                              |
| Schema    | `public`                              |
| Table     | `debtor_intelligence`                 |
| Return    | `All matching rows`                   |
| Filters   | `judgment_id` equals `{{ $json.id }}` |
| Order     | `created_at` descending               |
| Limit     | `1`                                   |

**Output** (example):

```json
{
  "id": "intel-uuid-...",
  "judgment_id": "a1b2c3d4-...",
  "data_source": "n8n_enrichment_v1",
  "employer_name": "ABC Manufacturing Inc.",
  "employer_address": "123 Industrial Way, Brooklyn, NY 11201",
  "income_band": "$50k-75k",
  "bank_name": "Chase Bank",
  "bank_address": "456 Main St, Brooklyn, NY 11215",
  "home_ownership": "owner",
  "has_benefits_only_account": false,
  "confidence_score": 78,
  "is_verified": false
}
```

---

### 4. Merge Judgment and Intelligence

**Node Type**: `n8n-nodes-base.merge`  
**Name**: `Merge Data`

**Configuration**:

| Field            | Value               |
| ---------------- | ------------------- |
| Mode             | `Combine`           |
| Combination Mode | `Merge By Position` |

**Purpose**: Combine judgment and intelligence into a single object for downstream processing.

---

### 5. Check Preconditions

**Node Type**: `n8n-nodes-base.code`  
**Name**: `Check Preconditions`

**Purpose**: Validate that the judgment is eligible for income execution.

**JavaScript Code**:

```javascript
const webhook = $items("Income Execution Webhook")[0].json.body;
const judgment = $items("Fetch Judgment")[0].json;
const intel = $items("Fetch Debtor Intelligence")[0]?.json || {};

const errors = [];

// 1. Check judgment exists
if (!judgment || !judgment.id) {
  errors.push("Judgment not found");
}

// 2. Check status is actionable (collectability_score >= 60)
if (judgment && (judgment.collectability_score || 0) < 60) {
  errors.push(
    `Judgment not actionable (collectability_score: ${
      judgment.collectability_score || 0
    })`
  );
}

// 3. Check employer_name exists
if (!intel.employer_name) {
  errors.push("Debtor intelligence missing employer_name");
}

// 4. Check income_band is not LOW
const lowIncomeBands = ["$0-25k", "LOW", "low", "unknown", null, ""];
if (lowIncomeBands.includes(intel.income_band)) {
  errors.push(`Income band too low for wage garnishment: ${intel.income_band}`);
}

// 5. Check for benefits-only account (CPLR 5222(d) exemption warning)
const hasExemptionWarning = intel.has_benefits_only_account === true;

const isValid = errors.length === 0;

return [
  {
    json: {
      is_valid: isValid,
      errors: errors,
      exemption_warning: hasExemptionWarning,
      judgment: judgment,
      intelligence: intel,
      webhook: webhook,
    },
  },
];
```

**Output**:

```json
{
  "is_valid": true,
  "errors": [],
  "exemption_warning": false,
  "judgment": {
    /* ... */
  },
  "intelligence": {
    /* ... */
  },
  "webhook": {
    /* ... */
  }
}
```

---

### 6. IF: Preconditions Met?

**Node Type**: `n8n-nodes-base.if`  
**Name**: `Preconditions Met?`

**Configuration**:

| Condition | Value                                |
| --------- | ------------------------------------ |
| Boolean   | `{{ $json.is_valid }}` equals `true` |

**True Branch** → Continue to PDF generation  
**False Branch** → Return error response

---

### 6a. Return Error Response (False Branch)

**Node Type**: `n8n-nodes-base.respondToWebhook`  
**Name**: `Return Error`

**Configuration**:

| Field         | Value |
| ------------- | ----- |
| Response Code | `400` |
| Response Body | JSON  |

**Response Body**:

```json
{
  "success": false,
  "errors": {{ $json.errors }},
  "message": "Income execution preconditions not met"
}
```

> Workflow ends here if preconditions fail.

---

### 7. Compute Current Balance

**Node Type**: `n8n-nodes-base.code`  
**Name**: `Compute Balance`

**Purpose**: Calculate total owed with 9% simple interest per NY CPLR 5004.

**JavaScript Code**:

```javascript
const data = $input.first().json;
const judgment = data.judgment;

const principal = parseFloat(judgment.principal_amount) || 0;
const interestRate = parseFloat(judgment.interest_rate) || 9.0;
const judgmentDate = new Date(judgment.judgment_date);
const today = new Date();

// Calculate days since judgment
const msPerDay = 24 * 60 * 60 * 1000;
const daysSinceJudgment = Math.floor((today - judgmentDate) / msPerDay);

// Simple interest formula: I = P * r * t
// Where t = days / 365
const interestAmount =
  principal * (interestRate / 100) * (daysSinceJudgment / 365);
const totalBalance = principal + interestAmount;

// Format currency
const formatCurrency = (amount) => {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(amount);
};

// Format date
const formatDate = (date) => {
  return date.toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
};

return [
  {
    json: {
      ...data,
      calculations: {
        principal: principal,
        principal_formatted: formatCurrency(principal),
        interest_rate: interestRate,
        days_since_judgment: daysSinceJudgment,
        interest_amount: Math.round(interestAmount * 100) / 100,
        interest_formatted: formatCurrency(interestAmount),
        total_balance: Math.round(totalBalance * 100) / 100,
        total_formatted: formatCurrency(totalBalance),
        execution_date: formatDate(today),
        judgment_date_formatted: formatDate(judgmentDate),
      },
    },
  },
];
```

**Output**:

```json
{
  "judgment": {
    /* ... */
  },
  "intelligence": {
    /* ... */
  },
  "calculations": {
    "principal": 8500,
    "principal_formatted": "$8,500.00",
    "interest_rate": 9,
    "days_since_judgment": 319,
    "interest_amount": 668.47,
    "interest_formatted": "$668.47",
    "total_balance": 9168.47,
    "total_formatted": "$9,168.47",
    "execution_date": "November 30, 2024",
    "judgment_date_formatted": "January 15, 2024"
  }
}
```

---

### 8. Download PDF Template

**Node Type**: `n8n-nodes-base.httpRequest`  
**Name**: `Download Template`

**Configuration**:

| Field           | Value                                                                                                     |
| --------------- | --------------------------------------------------------------------------------------------------------- |
| Method          | `GET`                                                                                                     |
| URL             | `{{ $env.SUPABASE_URL }}/storage/v1/object/enforcement-documents/templates/income_execution_template.pdf` |
| Response Format | `File`                                                                                                    |
| Output Property | `templatePdf`                                                                                             |

**Headers**:

```json
{
  "apikey": "{{ $env.SUPABASE_SERVICE_ROLE_KEY }}",
  "Authorization": "Bearer {{ $env.SUPABASE_SERVICE_ROLE_KEY }}"
}
```

---

### 9. Fill PDF with pdf-lib

**Node Type**: `n8n-nodes-base.code`  
**Name**: `Fill PDF Template`

**Purpose**: Use `pdf-lib` to fill the Income Execution form fields.

> **Note**: n8n Code nodes support `pdf-lib` via npm. Ensure the n8n instance has access to external npm modules or use a self-hosted n8n with `pdf-lib` installed.

**JavaScript Code**:

```javascript
// Import pdf-lib (available in n8n Code node)
const { PDFDocument, StandardFonts, rgb } = require("pdf-lib");

const data = $items("Compute Balance")[0].json;
const templateBuffer = $items("Download Template")[0].binary.templatePdf.data;

// Decode base64 template
const pdfBytes = Buffer.from(templateBuffer, "base64");

// Load the PDF
const pdfDoc = await PDFDocument.load(pdfBytes);
const form = pdfDoc.getForm();

// Get the Helvetica font for fallback text
const helvetica = await pdfDoc.embedFont(StandardFonts.Helvetica);

// Field mapping from our data to PDF form fields
const fieldValues = {
  court_name: data.judgment.court_name || "",
  case_index_number: data.judgment.case_index_number || "",
  creditor_name: data.judgment.original_creditor || "",
  debtor_name: data.judgment.debtor_name || "",
  judgment_date: data.calculations.judgment_date_formatted || "",
  principal_amount: data.calculations.principal_formatted || "",
  interest_amount: data.calculations.interest_formatted || "",
  total_balance: data.calculations.total_formatted || "",
  employer_name: data.intelligence.employer_name || "",
  employer_address: data.intelligence.employer_address || "",
  execution_date: data.calculations.execution_date || "",
  county: data.judgment.county || "",
};

// Fill each field
for (const [fieldName, value] of Object.entries(fieldValues)) {
  try {
    const field = form.getTextField(fieldName);
    if (field) {
      field.setText(value);
      field.updateAppearances(helvetica);
    }
  } catch (e) {
    // Field may not exist in template - log but continue
    console.log(`Field '${fieldName}' not found in PDF template`);
  }
}

// Flatten the form (make fields non-editable)
form.flatten();

// Save the filled PDF
const filledPdfBytes = await pdfDoc.save();
const filledPdfBase64 = Buffer.from(filledPdfBytes).toString("base64");

// Generate filename
const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
const filename = `income_execution_${data.judgment.case_index_number}_${timestamp}.pdf`;

return [
  {
    json: {
      ...data,
      generated_pdf: {
        filename: filename,
        content_type: "application/pdf",
        size_bytes: filledPdfBytes.length,
      },
    },
    binary: {
      filledPdf: {
        data: filledPdfBase64,
        mimeType: "application/pdf",
        fileName: filename,
      },
    },
  },
];
```

**Output**:

```json
{
  "judgment": {
    /* ... */
  },
  "calculations": {
    /* ... */
  },
  "generated_pdf": {
    "filename": "income_execution_2024-NY-12345_2024-11-30T14-00-00-000Z.pdf",
    "content_type": "application/pdf",
    "size_bytes": 125432
  }
}
```

Plus binary data in `filledPdf`.

---

### 10. Upload PDF to Supabase Storage

**Node Type**: `n8n-nodes-base.httpRequest`  
**Name**: `Upload to Storage`

**Configuration**:

| Field             | Value                                                                                                          |
| ----------------- | -------------------------------------------------------------------------------------------------------------- |
| Method            | `POST`                                                                                                         |
| URL               | `{{ $env.SUPABASE_URL }}/storage/v1/object/enforcement-documents/generated/{{ $json.generated_pdf.filename }}` |
| Body Content Type | `Raw`                                                                                                          |
| Binary Property   | `filledPdf`                                                                                                    |

**Headers**:

```json
{
  "apikey": "{{ $env.SUPABASE_SERVICE_ROLE_KEY }}",
  "Authorization": "Bearer {{ $env.SUPABASE_SERVICE_ROLE_KEY }}",
  "Content-Type": "application/pdf",
  "x-upsert": "true"
}
```

**Output**:

```json
{
  "Key": "enforcement-documents/generated/income_execution_2024-NY-12345_2024-11-30T14-00-00-000Z.pdf"
}
```

---

### 11. Build Storage URL

**Node Type**: `n8n-nodes-base.code`  
**Name**: `Build Storage URL`

**JavaScript Code**:

```javascript
const prevData = $items("Fill PDF Template")[0].json;
const uploadResult = $input.first().json;

const storageKey = uploadResult.Key;
const supabaseUrl = $env.SUPABASE_URL;

// Build the authenticated download URL
// For private buckets, use signed URLs or authenticated endpoint
const publicUrl = `${supabaseUrl}/storage/v1/object/authenticated/${storageKey}`;

// Alternative: Create a signed URL (valid for 7 days)
const signedUrlPath = `${supabaseUrl}/storage/v1/object/sign/enforcement-documents/generated/${prevData.generated_pdf.filename}`;

return [
  {
    json: {
      ...prevData,
      storage: {
        key: storageKey,
        public_url: publicUrl,
        filename: prevData.generated_pdf.filename,
      },
    },
  },
];
```

---

### 12. Insert Enforcement Action

**Node Type**: `n8n-nodes-base.supabase`  
**Name**: `Insert Enforcement Action`

**Configuration**:

| Field     | Value                 |
| --------- | --------------------- |
| Operation | `Insert`              |
| Schema    | `public`              |
| Table     | `enforcement_actions` |

**Columns**:

| Column                        | Value                                                                              |
| ----------------------------- | ---------------------------------------------------------------------------------- |
| `judgment_id`                 | `{{ $json.judgment.id }}`                                                          |
| `action_type`                 | `income_execution`                                                                 |
| `status`                      | `planned`                                                                          |
| `requires_attorney_signature` | `{{ $items('Income Execution Webhook')[0].json.body.require_attorney_signature }}` |
| `generated_url`               | `{{ $json.storage.public_url }}`                                                   |
| `notes`                       | `Auto-generated income execution document`                                         |
| `metadata`                    | See below                                                                          |

**Metadata JSON**:

```json
{
  "generated_at": "{{ new Date().toISOString() }}",
  "generated_by": "dragonfly_income_execution_factory_v1",
  "requested_by": "{{ $items('Income Execution Webhook')[0].json.body.requested_by }}",
  "calculations": {
    "principal": {{ $json.calculations.principal }},
    "interest_amount": {{ $json.calculations.interest_amount }},
    "total_balance": {{ $json.calculations.total_balance }},
    "days_since_judgment": {{ $json.calculations.days_since_judgment }}
  },
  "employer": {
    "name": "{{ $json.intelligence.employer_name }}",
    "address": "{{ $json.intelligence.employer_address }}"
  },
  "storage_key": "{{ $json.storage.key }}"
}
```

**Output**: Inserted row with `id`.

---

### 13. Prepare Email Content

**Node Type**: `n8n-nodes-base.code`  
**Name**: `Prepare Email`

**JavaScript Code**:

```javascript
const data = $items("Build Storage URL")[0].json;
const enforcementAction = $input.first().json;
const webhook = $items("Income Execution Webhook")[0].json.body;

const requiresSignature = webhook.require_attorney_signature;

const subject = `📋 Income Execution Ready: ${data.judgment.case_index_number}`;

const checklist = requiresSignature
  ? `
## ✅ Mailing Checklist

1. [ ] **Print** the attached Income Execution form (2 copies)
2. [ ] **Attorney signature required** - Have counsel sign both copies
3. [ ] **Attach filing fee** check payable to "Clerk of the Court" ($45)
4. [ ] **Prepare envelope** addressed to:
   - **${data.intelligence.employer_name}**
   - ${data.intelligence.employer_address}
5. [ ] **Mail** via Certified Mail, Return Receipt Requested
6. [ ] **File** copy with the court within 20 days of service
7. [ ] **Log** tracking number in the dashboard
`
  : `
## ✅ Mailing Checklist

1. [ ] **Print** the attached Income Execution form (2 copies)
2. [ ] **Attach filing fee** check payable to "Clerk of the Court" ($45)
3. [ ] **Prepare envelope** addressed to:
   - **${data.intelligence.employer_name}**
   - ${data.intelligence.employer_address}
4. [ ] **Mail** via Certified Mail, Return Receipt Requested
5. [ ] **File** copy with the court within 20 days of service
6. [ ] **Log** tracking number in the dashboard
`;

const body = `
# Income Execution Generated

**Case:** ${data.judgment.case_index_number}
**Debtor:** ${data.judgment.debtor_name}
**Creditor:** ${data.judgment.original_creditor}
**County:** ${data.judgment.county}

## 💰 Balance Summary

| Item | Amount |
|------|--------|
| Principal | ${data.calculations.principal_formatted} |
| Interest (${data.calculations.days_since_judgment} days @ 9%) | ${
  data.calculations.interest_formatted
} |
| **Total Due** | **${data.calculations.total_formatted}** |

## 🏢 Employer Details

- **Name:** ${data.intelligence.employer_name}
- **Address:** ${data.intelligence.employer_address}
- **Income Band:** ${data.intelligence.income_band || "Unknown"}

${
  data.exemption_warning
    ? "⚠️ **WARNING:** Debtor may have benefits-only bank account (CPLR 5222(d) exemption). Verify before proceeding."
    : ""
}

${checklist}

---

📎 **Document Link:** [Download Income Execution PDF](${
  data.storage.public_url
})

*Generated by Dragonfly Civil on ${data.calculations.execution_date}*
`;

return [
  {
    json: {
      email: {
        to: webhook.requested_by || "mom@dragonflycivil.com",
        subject: subject,
        body_markdown: body,
        body_html: body.replace(/\n/g, "<br>"), // Simple markdown to HTML
        attachment_url: data.storage.public_url,
        attachment_filename: data.storage.filename,
      },
      enforcement_action_id: enforcementAction.id,
      ...data,
    },
  },
];
```

---

### 14. Send Email to Mom

**Node Type**: `n8n-nodes-base.emailSend` (or `n8n-nodes-base.gmail` / `n8n-nodes-base.microsoftOutlook`)  
**Name**: `Send Email to Mom`

**Configuration** (using SMTP):

| Field        | Value                                            |
| ------------ | ------------------------------------------------ |
| From Email   | `automation@dragonflycivil.com`                  |
| To Email     | `{{ $json.email.to }}`                           |
| Subject      | `{{ $json.email.subject }}`                      |
| Email Format | `HTML`                                           |
| HTML Body    | `{{ $json.email.body_html }}`                    |
| Attachments  | Download from `{{ $json.email.attachment_url }}` |

> **Alternative**: Use SendGrid, Mailgun, or other email service nodes with better HTML rendering.

---

### 15. Return Success Response

**Node Type**: `n8n-nodes-base.respondToWebhook`  
**Name**: `Return Success`

**Configuration**:

| Field         | Value |
| ------------- | ----- |
| Response Code | `200` |
| Response Body | JSON  |

**Response Body**:

```json
{
  "success": true,
  "message": "Income execution document generated and emailed",
  "data": {
    "enforcement_action_id": "{{ $json.enforcement_action_id }}",
    "judgment_id": "{{ $json.judgment.id }}",
    "case_number": "{{ $json.judgment.case_index_number }}",
    "total_balance": {{ $json.calculations.total_balance }},
    "document_url": "{{ $json.storage.public_url }}",
    "emailed_to": "{{ $json.email.to }}"
  }
}
```

---

## Complete Node Connections

```
[1] Income Execution Webhook
         │
         ▼
[2] Fetch Judgment
         │
         ▼
[3] Fetch Debtor Intelligence
         │
         ▼
[4] Merge Data
         │
         ▼
[5] Check Preconditions
         │
         ▼
[6] Preconditions Met? ──(false)──► [6a] Return Error ──► END
         │
       (true)
         │
         ▼
[7] Compute Balance
         │
         ▼
[8] Download Template
         │
         ▼
[9] Fill PDF Template (pdf-lib)
         │
         ▼
[10] Upload to Storage
         │
         ▼
[11] Build Storage URL
         │
         ▼
[12] Insert Enforcement Action
         │
         ▼
[13] Prepare Email
         │
         ▼
[14] Send Email to Mom
         │
         ▼
[15] Return Success ──► END
```

---

## Required Credentials

| Credential Name         | Type         | Used By        |
| ----------------------- | ------------ | -------------- |
| `Supabase Service`      | Supabase API | Nodes 2, 3, 12 |
| `Supabase Storage Auth` | Header Auth  | Nodes 8, 10    |
| `SMTP / Email Service`  | Email        | Node 14        |
| `Webhook Auth`          | Header Auth  | Node 1         |

---

## Environment Variables

| Variable                             | Description                             |
| ------------------------------------ | --------------------------------------- |
| `SUPABASE_URL`                       | Supabase project URL                    |
| `SUPABASE_SERVICE_ROLE_KEY`          | Service role key                        |
| `MOM_EMAIL`                          | Default recipient email                 |
| `REQUIRE_ATTORNEY_SIGNATURE_DEFAULT` | Default value for signature requirement |

---

## Error Handling Checklist

- [ ] **Judgment not found**: Return 404 with clear message.
- [ ] **Intelligence missing**: Return 400 with specific field errors.
- [ ] **PDF template download failure**: Retry 3x, then alert ops.
- [ ] **pdf-lib errors**: Catch and log field mapping issues.
- [ ] **Storage upload failure**: Retry with exponential backoff.
- [ ] **Email send failure**: Log error, still return success (document was generated).

---

## Testing Checklist

1. **Happy path**: Valid judgment with employer → PDF generated, email sent.
2. **Low collectability**: `collectability_score < 60` → Return error.
3. **Missing employer**: No `employer_name` → Return error.
4. **Low income band**: `income_band = '$0-25k'` → Return error.
5. **Benefits warning**: `has_benefits_only_account = true` → Warning in email.
6. **Attorney signature flag**: Test both `true` and `false` paths.

---

## CPLR 5231 Compliance Notes

1. **Maximum Garnishment**: NY law limits wage garnishment to the lesser of:

   - 10% of gross wages, OR
   - The amount by which disposable earnings exceed 30× federal minimum wage

2. **Employer Duties**: Employer must begin withholding within 20 days of service.

3. **Filing Requirement**: A copy must be filed with the court.

4. **Exemptions**: Watch for CPLR 5222(d) exempt accounts (Social Security, SSI, etc.).

---

## Future Enhancements

1. **DocuSign Integration**: Replace manual signature with e-signature workflow.
2. **Court Filing API**: Auto-file with NYSCEF where available.
3. **Tracking Dashboard**: Show document status (draft → signed → filed → served).
4. **Batch Generation**: Process multiple judgments in one workflow run.
5. **Template Versioning**: Support multiple PDF templates per court/county.

---

_Last updated: November 2024_
