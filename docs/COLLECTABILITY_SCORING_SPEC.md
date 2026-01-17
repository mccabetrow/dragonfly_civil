# Collectability Scoring Specification

**Author:** CEO / Principal Engineer  
**Date:** January 2026  
**Version:** 1.0.0

---

## Overview

The **Collectability Score** is a 0-100 numeric rating that predicts the likelihood and value of successfully enforcing a judgment. Higher scores indicate "perfect plaintiffs" – cases where:

1. The judgment is substantial enough to warrant effort
2. The debtor is likely locatable and has attachable assets
3. The case is fresh enough for effective enforcement
4. Contact information enables outreach

---

## Scoring Formula

```
COLLECTABILITY_SCORE = SUM(component_scores) / MAX_POSSIBLE_SCORE * 100
```

Where components are:

| Component                  | Max Points | Weight                |
| -------------------------- | ---------- | --------------------- |
| **Judgment Amount**        | 30         | Primary driver of ROI |
| **Recency**                | 20         | Fresher = easier      |
| **Debtor Type**            | 15         | Business > Individual |
| **Address Completeness**   | 15         | Required for service  |
| **Contact Quality**        | 10         | Enables outreach      |
| **Employer/Asset Signals** | 10         | Garnishment potential |
| **TOTAL**                  | 100        |                       |

---

## Component Scoring Rules

### 1. Judgment Amount (30 points max)

Economic viability is paramount. Minimum threshold ensures ROI.

| Amount Range      | Points | Rationale                   |
| ----------------- | ------ | --------------------------- |
| < $1,000          | 0      | Below economic threshold    |
| $1,000 - $4,999   | 10     | Small claims, low margin    |
| $5,000 - $9,999   | 15     | Viable for standard process |
| $10,000 - $24,999 | 20     | Good economics              |
| $25,000 - $49,999 | 25     | Strong case                 |
| $50,000 - $99,999 | 28     | High value                  |
| ≥ $100,000        | 30     | Priority target             |

**SQL Implementation:**

```sql
CASE
    WHEN judgment_amount < 1000 THEN 0
    WHEN judgment_amount < 5000 THEN 10
    WHEN judgment_amount < 10000 THEN 15
    WHEN judgment_amount < 25000 THEN 20
    WHEN judgment_amount < 50000 THEN 25
    WHEN judgment_amount < 100000 THEN 28
    ELSE 30
END AS amount_score
```

### 2. Recency (20 points max)

Fresher judgments = better locate rates, less stale contact info.

| Age          | Points | Rationale            |
| ------------ | ------ | -------------------- |
| 0-30 days    | 20     | Optimal              |
| 31-90 days   | 18     | Still fresh          |
| 91-180 days  | 15     | Good                 |
| 181-365 days | 12     | Acceptable           |
| 1-2 years    | 8      | Aging                |
| 2-5 years    | 5      | Stale                |
| 5-10 years   | 2      | Very stale           |
| > 10 years   | 0      | Likely unenforceable |

**SQL Implementation:**

```sql
CASE
    WHEN days_since_judgment <= 30 THEN 20
    WHEN days_since_judgment <= 90 THEN 18
    WHEN days_since_judgment <= 180 THEN 15
    WHEN days_since_judgment <= 365 THEN 12
    WHEN days_since_judgment <= 730 THEN 8
    WHEN days_since_judgment <= 1825 THEN 5
    WHEN days_since_judgment <= 3650 THEN 2
    ELSE 0
END AS recency_score
```

### 3. Debtor Type (15 points max)

Businesses are easier to locate, garnish, and often have assets.

| Debtor Type                         | Points | Rationale                     |
| ----------------------------------- | ------ | ----------------------------- |
| Business (LLC, Corp, Inc)           | 15     | Public filings, bank accounts |
| Business (DBA/Sole Prop)            | 12     | Often has commercial assets   |
| Individual with business indicators | 10     | May have business income      |
| Individual                          | 8      | Standard                      |
| Unknown/Unclear                     | 5      | Need research                 |

**Detection Rules:**

- Contains "LLC", "Inc", "Corp", "LP", "LLP" → Business
- Contains "DBA", "d/b/a", "trading as" → DBA
- Contains business keywords ("Services", "Enterprises", "Holdings") → Business indicator
- Otherwise → Individual

**SQL Implementation:**

```sql
CASE
    WHEN debtor_name ~* '\b(LLC|INC|CORP|LP|LLP|CORPORATION|LIMITED)\b' THEN 15
    WHEN debtor_name ~* '\b(DBA|D/B/A|TRADING AS)\b' THEN 12
    WHEN debtor_name ~* '\b(SERVICES|ENTERPRISES|HOLDINGS|MANAGEMENT|CONSTRUCTION|CONTRACTING)\b' THEN 10
    WHEN debtor_name IS NOT NULL AND debtor_name != '' THEN 8
    ELSE 5
END AS debtor_type_score
```

### 4. Address Completeness (15 points max)

Full address enables service, skip tracing, asset searches.

| Address Quality                 | Points | Rationale           |
| ------------------------------- | ------ | ------------------- |
| Full (street, city, state, zip) | 15     | Ideal               |
| Partial (street + city or zip)  | 10     | Workable            |
| City/State only                 | 5      | Needs enhancement   |
| None                            | 0      | Requires skip trace |

**Detection Rules:**

- Has street number + street name + (city OR zip) → Full
- Has any two of (street, city, state, zip) → Partial
- Has only city/state → City/State only
- Empty → None

**SQL Implementation:**

```sql
CASE
    WHEN debtor_address ~* '\d+\s+\w+.*\b(NY|NJ|CT|PA|FL)\b.*\d{5}' THEN 15
    WHEN debtor_address ~* '\d+\s+\w+' AND debtor_address ~* '\d{5}' THEN 15
    WHEN debtor_address ~* '\d+\s+\w+' OR debtor_address ~* '\d{5}' THEN 10
    WHEN debtor_address IS NOT NULL AND LENGTH(debtor_address) > 5 THEN 5
    ELSE 0
END AS address_score
```

### 5. Contact Quality (10 points max)

Plaintiff contact info enables outreach for representation.

| Contact Level   | Points | Rationale               |
| --------------- | ------ | ----------------------- |
| Phone + Email   | 10     | Full contact ability    |
| Phone only      | 7      | Can call                |
| Email only      | 5      | Can email               |
| Attorney listed | 3      | Can contact via counsel |
| None            | 0      | Requires lookup         |

**SQL Implementation:**

```sql
CASE
    WHEN plaintiff_phone IS NOT NULL AND plaintiff_email IS NOT NULL THEN 10
    WHEN plaintiff_phone IS NOT NULL THEN 7
    WHEN plaintiff_email IS NOT NULL THEN 5
    WHEN attorney_name IS NOT NULL THEN 3
    ELSE 0
END AS contact_score
```

### 6. Employer/Asset Signals (10 points max)

Indicators that suggest garnishment or asset recovery potential.

| Signal                              | Points | Rationale                 |
| ----------------------------------- | ------ | ------------------------- |
| Employer mentioned in filing        | 5      | Wage garnishment possible |
| Business address (commercial lease) | 3      | Business assets           |
| Property indicators                 | 2      | Real property liens       |
| None detected                       | 0      | Standard                  |

**These signals are additive (max 10).**

**Detection Rules:**

- `employer` field populated OR debtor address contains business indicators
- Business/commercial address patterns
- Real property mentioned in case details

**SQL Implementation:**

```sql
LEAST(10,
    CASE WHEN employer_name IS NOT NULL THEN 5 ELSE 0 END +
    CASE WHEN debtor_address ~* '\b(SUITE|STE|FLOOR|FL|UNIT|#)\b' THEN 3 ELSE 0 END +
    CASE WHEN raw_payload::text ~* '\b(PROPERTY|REAL ESTATE|MORTGAGE)\b' THEN 2 ELSE 0 END
) AS asset_signal_score
```

---

## Priority Tiers

Based on collectability score, judgments are assigned to priority tiers:

| Tier             | Score Range | Priority  | Action            |
| ---------------- | ----------- | --------- | ----------------- |
| **A (Platinum)** | 80-100      | Immediate | Same-day outreach |
| **B (Gold)**     | 60-79       | High      | Within 48 hours   |
| **C (Silver)**   | 40-59       | Standard  | Within 1 week     |
| **D (Bronze)**   | 20-39       | Low       | Batch processing  |
| **F (Archive)**  | 0-19        | Skip      | Do not pursue     |

---

## Database Implementation

### Migration: Scoring Function

```sql
CREATE OR REPLACE FUNCTION public.compute_collectability_score(
    p_judgment_amount numeric,
    p_judgment_date date,
    p_debtor_name text,
    p_debtor_address text,
    p_plaintiff_phone text,
    p_plaintiff_email text,
    p_attorney_name text,
    p_employer_name text,
    p_raw_payload jsonb DEFAULT NULL
) RETURNS TABLE (
    total_score integer,
    amount_score integer,
    recency_score integer,
    debtor_type_score integer,
    address_score integer,
    contact_score integer,
    asset_signal_score integer,
    priority_tier text
) LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_days_since integer;
    v_amount_score integer := 0;
    v_recency_score integer := 0;
    v_debtor_type_score integer := 0;
    v_address_score integer := 0;
    v_contact_score integer := 0;
    v_asset_signal_score integer := 0;
    v_total integer := 0;
    v_tier text;
BEGIN
    -- Days since judgment
    v_days_since := COALESCE(CURRENT_DATE - p_judgment_date, 9999);

    -- 1. Amount Score (30 max)
    v_amount_score := CASE
        WHEN p_judgment_amount < 1000 THEN 0
        WHEN p_judgment_amount < 5000 THEN 10
        WHEN p_judgment_amount < 10000 THEN 15
        WHEN p_judgment_amount < 25000 THEN 20
        WHEN p_judgment_amount < 50000 THEN 25
        WHEN p_judgment_amount < 100000 THEN 28
        ELSE 30
    END;

    -- 2. Recency Score (20 max)
    v_recency_score := CASE
        WHEN v_days_since <= 30 THEN 20
        WHEN v_days_since <= 90 THEN 18
        WHEN v_days_since <= 180 THEN 15
        WHEN v_days_since <= 365 THEN 12
        WHEN v_days_since <= 730 THEN 8
        WHEN v_days_since <= 1825 THEN 5
        WHEN v_days_since <= 3650 THEN 2
        ELSE 0
    END;

    -- 3. Debtor Type Score (15 max)
    v_debtor_type_score := CASE
        WHEN p_debtor_name ~* '\b(LLC|INC|CORP|LP|LLP|CORPORATION|LIMITED)\b' THEN 15
        WHEN p_debtor_name ~* '\b(DBA|D/B/A|TRADING AS)\b' THEN 12
        WHEN p_debtor_name ~* '\b(SERVICES|ENTERPRISES|HOLDINGS|MANAGEMENT|CONSTRUCTION|CONTRACTING|REALTY|PROPERTIES)\b' THEN 10
        WHEN p_debtor_name IS NOT NULL AND p_debtor_name != '' THEN 8
        ELSE 5
    END;

    -- 4. Address Score (15 max)
    v_address_score := CASE
        WHEN p_debtor_address ~* '\d+\s+\w+.*\b(NY|NJ|CT|PA|FL|CA|TX)\b.*\d{5}' THEN 15
        WHEN p_debtor_address ~* '\d+\s+\w+' AND p_debtor_address ~* '\d{5}' THEN 15
        WHEN p_debtor_address ~* '\d+\s+\w+' OR p_debtor_address ~* '\d{5}' THEN 10
        WHEN p_debtor_address IS NOT NULL AND LENGTH(p_debtor_address) > 5 THEN 5
        ELSE 0
    END;

    -- 5. Contact Score (10 max)
    v_contact_score := CASE
        WHEN p_plaintiff_phone IS NOT NULL AND p_plaintiff_email IS NOT NULL THEN 10
        WHEN p_plaintiff_phone IS NOT NULL THEN 7
        WHEN p_plaintiff_email IS NOT NULL THEN 5
        WHEN p_attorney_name IS NOT NULL THEN 3
        ELSE 0
    END;

    -- 6. Asset Signal Score (10 max)
    v_asset_signal_score := LEAST(10,
        CASE WHEN p_employer_name IS NOT NULL AND p_employer_name != '' THEN 5 ELSE 0 END +
        CASE WHEN p_debtor_address ~* '\b(SUITE|STE|FLOOR|FL|UNIT|#)\b' THEN 3 ELSE 0 END +
        CASE WHEN p_raw_payload IS NOT NULL AND p_raw_payload::text ~* '\b(PROPERTY|REAL ESTATE|MORTGAGE|LIEN)\b' THEN 2 ELSE 0 END
    );

    -- Total
    v_total := v_amount_score + v_recency_score + v_debtor_type_score +
               v_address_score + v_contact_score + v_asset_signal_score;

    -- Priority Tier
    v_tier := CASE
        WHEN v_total >= 80 THEN 'A'
        WHEN v_total >= 60 THEN 'B'
        WHEN v_total >= 40 THEN 'C'
        WHEN v_total >= 20 THEN 'D'
        ELSE 'F'
    END;

    RETURN QUERY SELECT
        v_total,
        v_amount_score,
        v_recency_score,
        v_debtor_type_score,
        v_address_score,
        v_contact_score,
        v_asset_signal_score,
        v_tier;
END;
$$;
```

---

## Example Calculations

### Example 1: Perfect Plaintiff (Score: 95)

| Field     | Value                             | Score           |
| --------- | --------------------------------- | --------------- |
| Amount    | $75,000                           | 28              |
| Days old  | 15                                | 20              |
| Debtor    | "ABC Construction LLC"            | 15              |
| Address   | "123 Main St, Brooklyn, NY 11201" | 15              |
| Contact   | Phone + Email                     | 10              |
| Signals   | Employer known + Suite            | 7               |
| **TOTAL** |                                   | **95 (Tier A)** |

### Example 2: Average Plaintiff (Score: 52)

| Field     | Value          | Score           |
| --------- | -------------- | --------------- |
| Amount    | $8,500         | 15              |
| Days old  | 120            | 15              |
| Debtor    | "John Smith"   | 8               |
| Address   | "Brooklyn, NY" | 5               |
| Contact   | Attorney only  | 3               |
| Signals   | None           | 0               |
| **TOTAL** |                | **46 (Tier C)** |

### Example 3: Poor Plaintiff (Score: 15)

| Field     | Value   | Score           |
| --------- | ------- | --------------- |
| Amount    | $800    | 0               |
| Days old  | 2,000   | 5               |
| Debtor    | Unknown | 5               |
| Address   | None    | 0               |
| Contact   | None    | 0               |
| Signals   | None    | 0               |
| **TOTAL** |         | **10 (Tier F)** |

---

## Verification Queries

### Distribution by Tier

```sql
SELECT
    (compute_collectability_score(
        judgment_amount, judgment_entered_at::date, debtor_name, debtor_address,
        plaintiff_phone, plaintiff_email, attorney_name, employer_name, raw_payload
    )).priority_tier as tier,
    COUNT(*) as count,
    ROUND(AVG((compute_collectability_score(
        judgment_amount, judgment_entered_at::date, debtor_name, debtor_address,
        plaintiff_phone, plaintiff_email, attorney_name, employer_name, raw_payload
    )).total_score), 1) as avg_score
FROM plaintiff_leads
GROUP BY 1
ORDER BY 1;
```

### Top 20 Leads

```sql
SELECT
    id,
    plaintiff_name,
    debtor_name,
    judgment_amount,
    judgment_entered_at,
    score.*
FROM plaintiff_leads pl
CROSS JOIN LATERAL compute_collectability_score(
    pl.judgment_amount, pl.judgment_entered_at::date, pl.debtor_name, pl.debtor_address,
    pl.plaintiff_phone, pl.plaintiff_email, pl.attorney_name, pl.employer_name, pl.raw_payload
) score
ORDER BY score.total_score DESC
LIMIT 20;
```

---

## Future Enhancements

1. **ML-based scoring** - Train on historical collection success rates
2. **Asset verification** - Integrate property records, UCC filings
3. **Skip trace integration** - Real-time address/phone verification
4. **Debtor financial scoring** - Credit indicators (if legally available)
5. **Attorney quality signals** - Track attorney success rates

---

_This specification is versioned. Changes require documentation and migration._
