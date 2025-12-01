# Enforcement Tiers

Dragonfly enforces thousands of judgments with varying balances, debtor profiles, and asset signals. Tiers allow operators and automations to align effort with expected collectability. Tier calculations should be refreshed nightly using the canonical views (`v_enforcement_overview`, `v_enforcement_recent`, scoring outputs) so the Ops Console always reflects the latest status.

| Tier                          | Working Definition                                                               | Quantitative Criteria (example defaults)                                                               | Qualitative Signals                                                                        | Recommended Cadence & Actions                                                                                                                                                   |
| ----------------------------- | -------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Tier 0 — Monitor              | Fresh intake or dormant matters not yet ready for enforcement.                   | `collectability_score < 35` **or** `judgment_balance < $5k` **and** no asset hints.                    | Debtor unresponsive, missing contact data, plaintiff still validating paperwork.           | Keep in `pre_enforcement` stage, schedule data completion tasks, run skip-trace + asset sweeps quarterly, auto-close enforcement case if untouched for 6 months.                |
| Tier 1 — Warm Prospects       | Low-to-moderate balances with validated debtors and at least one contact vector. | `35 ≤ collectability_score < 60`, `judgment_balance $5k–$15k`, consumer debtor.                        | Employer identified, recent call activity, bank lead but no confirmed funds.               | Maintain monthly asset refresh, run automated asset search workflow, prep subpoenas but hold levy until funds confirmed, call cadence weekly.                                   |
| Tier 2 — Active Enforcement   | High-balance or high-score cases where we have actionable assets.                | `60 ≤ collectability_score < 80` **or** `judgment_balance $15k–$50k`, commercial debtor with accounts. | Marshal intel, verified bank account, payroll contact, voluntary payment attempts stalled. | Trigger levy or garnishment flow within 5 business days, require enforcement event logging for every contact, escalate to marshal when levy hits.                               |
| Tier 3 — Strategic / Priority | Top recoveries warranting bespoke strategy and executive oversight.              | `collectability_score ≥ 80` **or** `judgment_balance ≥ $50k`, multiple open assets, repeat debtor.     | Asset map complete, legal leverage (liens, injunctions), board-level visibility.           | Dedicated enforcement case manager, run asset search + subpoena in parallel, marshal execution scheduled, weekly exec review, document every enforcement event within 24 hours. |

## Tier Assignment Inputs

1. **Collectability Score** – produced by analytics pipeline; ensure stored on `enforcement_cases.collectability_score` (float 0–100).
2. **Judgment Balance Buckets** – use `judgments.balance_due` or `enforcement_cases.current_balance`.
3. **Debtor Type** – individual vs entity from `plaintiffs` or debtor detail table.
4. **Asset Hints** – compiled from enforcement events (`asset_discovery`, `bank_lead`, `employer_lead`). Track boolean flags on `enforcement_cases` for quick filtering.
5. **Activity Freshness** – days since last `enforcement_events` entry; stale records should auto-demote a tier.

## Tier Governance

- Recompute nightly via stored procedure or worker (e.g., `select public.compute_enforcement_tiers()`), writing `tier`, `tier_reason`, `tier_as_of` to `enforcement_cases`.
- Manual overrides allowed; store `tier_override`, `override_expires_at`, `override_note` to respect executive decisions.
- Ops Console badges should surface tier + next recommended action (see flows doc).
- Reporting: `v_enforcement_overview` should expose aggregated counts per tier + total balance to guide staffing.
