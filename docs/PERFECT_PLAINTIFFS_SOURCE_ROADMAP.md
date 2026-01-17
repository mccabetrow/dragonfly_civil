# Perfect Plaintiffs Engine: Source Roadmap

**Author:** CEO / Principal Engineer  
**Date:** January 2026  
**Status:** Production Pilot

---

## Executive Summary

The **Perfect Plaintiffs Engine** is Dragonfly Civil's proprietary plaintiff sourcing system. Unlike vendor feeds (Simplicity, JBI), we source judgments directly from court systems, giving us:

- **Fresher data** (daily vs weekly/monthly vendor updates)
- **Complete control** over data quality and coverage
- **Zero vendor fees** at scale
- **Competitive moat** through unique data access

This document outlines the 3-tier source strategy, starting with New York civil courts.

---

## Tier 1: Fast, Reliable Access (No Scraping)

**Timeline:** Q1 2026 (Pilot)  
**Effort:** Low-Medium  
**Risk:** Low

These sources have official APIs, bulk download options, or stable machine-readable formats.

### 1.1 NY eCourts WebCivil (Primary Pilot Source)

| Attribute     | Value                                                |
| ------------- | ---------------------------------------------------- |
| **URL**       | https://iapps.courts.state.ny.us/webcivil/FCASSearch |
| **Data**      | Civil judgments, small claims, commercial division   |
| **Freshness** | Same-day or next-day                                 |
| **Access**    | Public web portal, no login required                 |
| **Format**    | Structured HTML (parseable)                          |
| **Coverage**  | All 62 NY counties                                   |

**Pilot Scope:**

- County: Kings County (Brooklyn) - High volume, good test case
- Case Type: Money Judgments only
- Date Range: Last 18 months
- Cadence: Daily deltas (new judgments filed/entered)

**Technical Approach:**

```
WebCivil Search → Parse HTML tables → Extract structured fields → Land in judgments_raw
```

**Key Fields Available:**

- Index Number (case ID)
- Parties (plaintiff/defendant names)
- Filing Date
- Judgment Date
- Judgment Amount
- Attorney Information

### 1.2 NY Unified Court System (UCS) Open Data Portal

| Attribute     | Value                                    |
| ------------- | ---------------------------------------- |
| **URL**       | https://ww2.nycourts.gov/open-data-21287 |
| **Data**      | Bulk civil case filings and dispositions |
| **Freshness** | Monthly/quarterly bulk updates           |
| **Access**    | Public download, some data via FOIL      |
| **Format**    | CSV, Excel                               |
| **Coverage**  | Statewide                                |

**Use Case:** Backfill historical data, validate WebCivil scraping accuracy.

### 1.3 County Clerk E-Filing Systems

Select counties have e-filing portals with search APIs:

| County              | Portal | Access |
| ------------------- | ------ | ------ |
| Nassau              | NYSCEF | Public |
| Suffolk             | NYSCEF | Public |
| Erie (Buffalo)      | NYSCEF | Public |
| Onondaga (Syracuse) | NYSCEF | Public |

**Note:** NYSCEF (New York State Courts Electronic Filing) is expanding. Counties on NYSCEF have structured, searchable data.

### 1.4 Federal PACER (Future)

| Attribute     | Value                                            |
| ------------- | ------------------------------------------------ |
| **URL**       | https://pacer.uscourts.gov                       |
| **Data**      | Federal civil judgments                          |
| **Freshness** | Real-time                                        |
| **Access**    | API, per-page fee ($0.10/page, capped at $3/doc) |
| **Coverage**  | All federal districts                            |

**Consideration:** PACER costs add up. Best for high-value federal judgments (>$50K).

---

## Tier 2: Moderate Scraping Required

**Timeline:** Q2-Q3 2026  
**Effort:** Medium  
**Risk:** Medium

These sources require web scraping with session handling, pagination, and rate limiting.

### 2.1 NYC Civil Court eCourts

| Attribute     | Value                                             |
| ------------- | ------------------------------------------------- |
| **URL**       | https://www.nycourts.gov/courts/nyc/civil/        |
| **Data**      | NYC Civil Court judgments (small claims, housing) |
| **Challenge** | Dynamic forms, session cookies                    |
| **Solution**  | Headless browser (Playwright)                     |

### 2.2 Other State Court Portals

| State        | Portal                    | Judgment Types      |
| ------------ | ------------------------- | ------------------- |
| New Jersey   | ACMS/eCourts              | Civil, small claims |
| Connecticut  | Civil/Family Case Look-Up | Civil judgments     |
| Pennsylvania | UJS Portal                | Civil, judgments    |
| Florida      | Various county clerks     | Civil judgments     |

**Strategy:** After NY pilot proves model, expand state-by-state.

### 2.3 County Recorder/Clerk Abstract Indices

Many counties publish judgment abstracts (liens) in searchable databases:

- These show when a judgment has been "docketed" (recorded as a lien)
- More reliable for enforceability than raw filings
- Often separate from court case systems

### 2.4 Judgment Lien Registries

Some states maintain central judgment lien registries:

| State      | Registry                                     | Coverage      |
| ---------- | -------------------------------------------- | ------------- |
| California | Secretary of State                           | Statewide EJL |
| Texas      | County-by-county                             | Varies        |
| Florida    | CCIS (Comprehensive Case Information System) | Statewide     |

---

## Tier 3: High Moat, Long-Term (Partnerships, FOIL, Bulk)

**Timeline:** 2027+  
**Effort:** High  
**Risk:** Low (once established)

These sources create durable competitive advantages but require significant upfront investment.

### 3.1 FOIL Requests (Freedom of Information Law)

**Strategy:** Submit bulk data requests to county clerks and court administrators.

| Advantage             | Detail                             |
| --------------------- | ---------------------------------- |
| **Complete data**     | No scraping gaps                   |
| **Historical depth**  | Can request 5+ years               |
| **Structured format** | Often receive CSV/database exports |
| **Legal right**       | Public records, must be provided   |

**Targets:**

- NY OCA (Office of Court Administration) - Statewide judgment data
- Individual county clerks - Docketed judgment abstracts
- City Marshals/Sheriffs - Execution records

**Cost:** $0-$500 per request (reproduction fees)  
**Timeline:** 2-6 weeks per request

### 3.2 Data Partnerships

| Partner Type                     | Value                             | Approach                |
| -------------------------------- | --------------------------------- | ----------------------- |
| **Title Companies**              | Judgment search databases         | B2B data sharing        |
| **Collection Agencies**          | Historical judgment lists         | Portfolio acquisition   |
| **Legal Data Vendors**           | Bulk case data                    | Licensing               |
| **Court Modernization Projects** | Early access to digitized records | Government partnerships |

### 3.3 Court E-Filing Integration

As courts modernize, some offer API access to licensed vendors:

- NY NYSCEF API (if opened to third parties)
- LexisNexis CourtLink integration
- Tyler Technologies Odyssey systems

### 3.4 Judgment Purchaser Networks

Partner with judgment buyers who receive bulk transfer data:

- They see filings before public records
- Mutually beneficial: we help collect, they share leads

---

## Pilot Implementation: NY Kings County

### Scope

| Parameter           | Value                           |
| ------------------- | ------------------------------- |
| **State**           | New York                        |
| **County**          | Kings (Brooklyn)                |
| **Case Type**       | Money Judgments (Civil Supreme) |
| **Date Range**      | 18 months lookback              |
| **Delta Frequency** | Daily                           |
| **Target Volume**   | ~500-2,000 judgments/day        |

### Data Flow

```
┌─────────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│   NY WebCivil       │────▶│   ny_judgments_     │────▶│   judgments_raw     │
│   (Source Portal)   │     │   pilot worker      │     │   (Landing Zone)    │
└─────────────────────┘     └─────────────────────┘     └─────────────────────┘
                                      │
                                      ▼
                            ┌─────────────────────┐     ┌─────────────────────┐
                            │  plaintiff_         │────▶│   plaintiff_leads   │
                            │  targeting worker   │     │   (Prioritized)     │
                            └─────────────────────┘     └─────────────────────┘
```

### Success Metrics

| Metric              | Target                 | Measurement                                |
| ------------------- | ---------------------- | ------------------------------------------ |
| **Daily coverage**  | >95% of new judgments  | Spot-check vs manual search                |
| **Data accuracy**   | >99% field accuracy    | Sample audit                               |
| **Latency**         | <24 hours from filing  | Compare judgment_entered_at to captured_at |
| **Uptime**          | >99% of scheduled runs | ingest_runs success rate                   |
| **Dedupe accuracy** | 0 duplicate judgments  | UNIQUE constraint violations               |

---

## Expansion Roadmap

### Phase 1: NY Pilot (Q1 2026)

- Kings County money judgments
- Validate architecture
- Tune collectability scoring

### Phase 2: NY Expansion (Q2 2026)

- Add Queens, Manhattan, Bronx, Nassau
- Add small claims, commercial division
- Submit FOIL for historical data

### Phase 3: Multi-State (Q3-Q4 2026)

- New Jersey (ACMS)
- Connecticut
- Florida (high volume)

### Phase 4: Scale (2027)

- PACER integration (federal)
- 10+ states
- Data partnerships

---

## Risk Mitigation

| Risk               | Mitigation                                                         |
| ------------------ | ------------------------------------------------------------------ |
| **Portal changes** | Content hash detection, alerting on >10% failure rate              |
| **Rate limiting**  | Respectful delays (1-2s between requests), rotate user agents      |
| **IP blocking**    | Residential proxy rotation, cloud IP diversity                     |
| **Legal/ToS**      | Public records are public, but consult counsel on automated access |
| **Data quality**   | Validation rules, reconciliation queries, sample audits            |

---

## Next Steps

1. ✅ Infrastructure complete (`judgments_raw`, `ingest_runs`, worker skeleton)
2. ⏳ Implement WebCivil scraper (awaiting portal access confirmation)
3. ⏳ Build plaintiff_targeting worker
4. ⏳ Define collectability scoring spec
5. ⏳ Deploy to Railway cron for daily runs
6. ⏳ Submit Kings County FOIL as parallel track

---

_This roadmap is a living document. Update as sources are validated and expanded._
