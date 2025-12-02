# UX Copy Rewrite Summary

**Date:** December 1, 2024  
**Goal:** Make the Mom Enforcement Console clear, empathetic, and procedural for the first operator (mom).

---

## Pages Updated

### 1. OverviewPage.tsx

| Before                                                          | After                                                   |
| --------------------------------------------------------------- | ------------------------------------------------------- |
| "Executive Summary"                                             | "Today's Snapshot"                                      |
| "Cases in pipeline"                                             | "Total judgments"                                       |
| "Total judgment value"                                          | "Total value of all judgments"                          |
| "Pipeline by Collectability Tier"                               | "Your Cases by Priority"                                |
| Tier A: "High collectability — asset-rich or responsive debtor" | "Best chances to collect — focus here first"            |
| Tier B: "Moderate — partial signals present"                    | "Worth pursuing — keep these moving"                    |
| Tier C: "Long tail — limited current data"                      | "Lower priority — check back later"                     |
| Empty urgent actions: "No tier-A cases yet."                    | "Great news — no urgent cases need attention right now" |
| Empty tasks: "No tasks scheduled for today."                    | "Nothing scheduled today — check back tomorrow"         |

### 2. CollectabilityPage.tsx

| Before                                                                 | After                                                   |
| ---------------------------------------------------------------------- | ------------------------------------------------------- |
| "High Collectability"                                                  | "Best Chances"                                          |
| "Moderate Collectability"                                              | "Worth Pursuing"                                        |
| "Long Tail"                                                            | "Lower Priority"                                        |
| Tier A description: "Strong signals — asset-rich or responsive debtor" | "Strong chance of collecting — focus here"              |
| Tier B description: "Moderate signals — partial data"                  | "Decent odds — keep these moving"                       |
| Tier C description: "Long tail — limited info, lower priority"         | "Lower odds for now — revisit later"                    |
| Filter help: "Filter by collectability tier (A, B, C)"                 | "A = best bets, B = worth pursuing, C = lower priority" |
| Empty state: "No cases in this collectability tier"                    | "No cases here yet — check another tab"                 |

### 3. CasesPage.tsx

| Before                                            | After                                                                                      |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| Tier descriptions: All started with "Supabase..." | Removed all Supabase references                                                            |
| "Recent FOIL responses"                           | "Public Records Responses"                                                                 |
| Empty cases: "No cases match the current filters" | "No cases yet — your first judgments will appear here once we import them from Simplicity" |
| "0 cases found"                                   | "No matching cases"                                                                        |
| "Debtor lookup history"                           | "Debtor Search History"                                                                    |
| Empty debtor lookup: "No debtor lookups yet"      | "No debtor searches yet — searches will show here as you work"                             |

### 4. HelpPage.tsx (Complete Rewrite)

Replaced entire developer-focused "Demo Guide" with user-friendly "Getting Started" guide.

**New sections:**

1. **Start with the Overview** — Explains dashboard metrics and urgent actions
2. **Understand the Tiers** — Clear A/B/C priority explanation
3. **Browse Your Cases** — How to use search and filters
4. **Track Public Records** — What public records are and why they matter
5. **Daily Workflow** — Step-by-step morning routine

**Removed all references to:**

- VS Code tasks, CLI commands, `make smoke`, `db_push.ps1`
- Supabase, n8n, technical migrations
- Developer terminology

---

## Shared Components Updated

### DashboardError.tsx

| Before                                                                                                  | After                                                      |
| ------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| Default helper text: "Run ./scripts/db_push.ps1 then rerun make smoke; ping #dragonfly if it persists." | No default helper text (only shows if explicitly provided) |

---

## Tone Guidelines Applied

- **Clear:** Plain language anyone can understand
- **Empathetic:** Friendly, encouraging empty states
- **Procedural:** Step-by-step guidance for new users
- **No jargon:** Removed all technical terms (Supabase, CLI, migrations, n8n, etc.)
