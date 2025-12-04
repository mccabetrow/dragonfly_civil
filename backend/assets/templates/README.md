# Legal Packet Templates

This directory contains DOCX templates for court-ready enforcement documents.

## Required Templates

Place the following templates here (created by legal team):

1. **`income_execution_ny.docx`** - Income Execution for New York
2. **`info_subpoena_ny.docx`** - Information Subpoena for New York

## Template Variables

Templates use Jinja2-style tags. Available variables:

### Judgment Data

- `{{ plaintiff_name }}` - Name of the plaintiff
- `{{ defendant_name }}` - Name of the defendant
- `{{ case_number }}` - Court case number
- `{{ judgment_amount_formatted }}` - e.g., "$25,000.00"
- `{{ judgment_date_formatted }}` - e.g., "10/15/2024"
- `{{ court }}` - Court name (if available)
- `{{ county }}` - County (if available)

### Defendant Contact (if available)

- `{{ defendant_address }}`
- `{{ defendant_phone }}`
- `{{ defendant_email }}`

### Enrichment Data (if available)

- `{{ employer_name }}` - Employer name
- `{{ employer_address }}` - Employer address
- `{{ bank_name }}` - Bank name
- `{{ bank_address }}` - Bank address

### Interest Calculations

- `{{ interest_rate_percent }}` - Annual rate (e.g., 9.0)
- `{{ interest_amount_formatted }}` - e.g., "$1,234.56"
- `{{ total_with_interest_formatted }}` - Principal + interest
- `{{ days_since_judgment }}` - Days elapsed
- `{{ years_since_judgment }}` - Years elapsed (decimal)

### Metadata

- `{{ generated_at }}` - Timestamp of generation
- `{{ generated_date }}` - Date of generation (MM/DD/YYYY)

## Example Usage in Template

```
INCOME EXECUTION

Plaintiff: {{ plaintiff_name }}
vs.
Defendant: {{ defendant_name }}

Case Number: {{ case_number }}

Original Judgment Amount: {{ judgment_amount_formatted }}
Date of Judgment: {{ judgment_date_formatted }}
Interest Rate: {{ interest_rate_percent }}%
Interest Accrued: {{ interest_amount_formatted }}
Total Amount Due: {{ total_with_interest_formatted }}

{% if employer_name %}
Employer: {{ employer_name }}
Employer Address: {{ employer_address }}
{% endif %}
```

## Notes

- Templates are rendered using `docxtpl` (python-docx + Jinja2)
- Use `{% if variable %}...{% endif %}` for conditional sections
- Use `{% for item in list %}...{% endfor %}` for lists (if needed)
- Confirm interest rate with counsel (NY CPLR 5004 prescribes 9% as of 2024)
