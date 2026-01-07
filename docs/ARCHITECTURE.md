# Dragonfly Civil — North Star Architecture

> _"A system that cannot explain itself cannot be trusted."_

This document defines the canonical architecture for Dragonfly Civil, the judgment-enforcement operating system. All contributions must respect the boundaries defined herein.

---

## I. The 4 Planes

Dragonfly is organized into four distinct **Planes**, each with clear responsibilities, technology ownership, and security contracts.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           OPS PLANE                                     │
│         CI/CD • Alerts • Gates • Runbooks • Monitoring                 │
│                    "Automated Governance"                               │
├─────────────────────────────────────────────────────────────────────────┤
│                        EXPERIENCE PLANE                                 │
│              Vercel Frontend • PostgREST • Read-Only                   │
│                    "Never Holds Secrets"                                │
├─────────────────────────────────────────────────────────────────────────┤
│                         SERVICE PLANE                                   │
│         Railway API • Workers • ETL • Scoring Engine                   │
│                  "The Only Writer of Truth"                            │
├─────────────────────────────────────────────────────────────────────────┤
│                          DATA PLANE                                     │
│          Supabase Postgres • Storage • RLS • Audit Logs                │
│                    "The Single Source of Truth"                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

### 1. Data Plane — _Source of Truth_

| Attribute          | Value                                                                    |
| ------------------ | ------------------------------------------------------------------------ |
| **Responsibility** | Persistent storage, schema integrity, access control                     |
| **Technology**     | Supabase Postgres, Row-Level Security (RLS), Storage Buckets, Audit Logs |
| **Location**       | `supabase/migrations/`, canonical views (`v_*`)                          |

**Rules:**

- ✅ The Data Plane is the **single source of truth** for all judgment and plaintiff data.
- ✅ All tables enforce **RLS** — no anonymous access to sensitive data.
- ✅ Schema changes require migrations in `supabase/migrations/`.
- ❌ The Data Plane **never trusts the Service Plane blindly** — constraints and triggers validate all writes.

**Canonical Objects:**

- `public.judgments` — Every judgment record
- `public.plaintiffs` — Plaintiff master data
- `public.plaintiff_contacts` — Contact information
- `public.v_plaintiffs_overview` — Dashboard aggregate view
- `public.v_enforcement_overview` — Enforcement metrics view
- `public.v_judgment_pipeline` — Pipeline status view

---

### 2. Service Plane — _Business Logic_

| Attribute          | Value                                                     |
| ------------------ | --------------------------------------------------------- |
| **Responsibility** | Mutations, business rules, scoring, ingestion, escalation |
| **Technology**     | Python (FastAPI), Railway, Background Workers             |
| **Location**       | `backend/`, `etl/`, `workers/`, `brain/`                  |

**Rules:**

- ✅ The Service Plane is the **only layer with write access** to critical tables.
- ✅ All mutations are **transactional** — partial writes are never committed.
- ✅ Workers use the **service role** key (never exposed to frontend).
- ❌ The Service Plane **never exposes credentials** to the Experience Plane.

**Key Components:**

- `backend/main.py` — FastAPI application entry
- `backend/workers/` — Background job processors
- `etl/src/plaintiff_importer.py` — Plaintiff ingestion pipeline
- `brain/escalation_engine.py` — Priority & escalation logic

---

### 3. Experience Plane — _User Interface_

| Attribute          | Value                                                       |
| ------------------ | ----------------------------------------------------------- |
| **Responsibility** | Data visualization, user interaction, read-heavy operations |
| **Technology**     | React (Vite), TypeScript, Vercel, PostgREST                 |
| **Location**       | `dragonfly-dashboard/`                                      |

**Rules:**

- ✅ **Read-only preference** — fetch via PostgREST for speed.
- ✅ **Dual-source resilience** — fallback to Service Plane API if PostgREST is unavailable.
- ✅ **Never holds secrets** — all API keys are `anon` role only.
- ❌ The Experience Plane **never writes directly** to the Data Plane (except through RLS-protected PostgREST endpoints).

**Key Components:**

- `dragonfly-dashboard/src/` — React application
- `dragonfly-dashboard/src/lib/supabase.ts` — Supabase client (anon key)
- `dragonfly-dashboard/src/hooks/` — Data fetching hooks with fallback logic

---

### 4. Ops Plane — _Reliability_

| Attribute          | Value                                                        |
| ------------------ | ------------------------------------------------------------ |
| **Responsibility** | Deployment, monitoring, alerting, governance automation      |
| **Technology**     | GitHub Actions, PowerShell, Discord Webhooks, Python tooling |
| **Location**       | `.github/workflows/`, `scripts/`, `tools/`                   |

**Rules:**

- ✅ The Ops Plane has **automated governance** over the other three planes.
- ✅ All deployments are **gated** — no production push without passing preflight.
- ✅ Alerts are **self-reporting** — Discord notifications for critical events.
- ❌ The Ops Plane **never modifies data directly** — only orchestrates and observes.

**Key Components:**

- `scripts/certify_readiness.ps1` — Go-Live certification
- `tools/go_live_gate.py` — Production readiness orchestrator
- `tools/doctor.py` — Health check suite
- `.github/workflows/lint_gate.yml` — CI lint enforcement

---

## II. The Data Flow — _Golden Path_

The canonical data flow through Dragonfly follows the **Golden Path**:

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   INGEST     │───▶│   SERVICE    │───▶│    DATA      │───▶│  EXPERIENCE  │
│  (CSV/API)   │    │  (Transform) │    │   (Store)    │    │  (Display)   │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
     │                    │                    │                    │
     │                    │                    │                    │
   Vendor             Validate              Persist              Read-only
   Export             Score                 Index                 View
                      Enrich                Audit
```

**Steps:**

1. **Ingest** — External data arrives via CSV drop (`data_in/`) or API endpoint.
2. **Service** — ETL pipeline validates, transforms, scores, and enriches.
3. **Data** — Processed records are written to Postgres with full audit trail.
4. **Experience** — Dashboard reads from canonical views via PostgREST.

**Validation Points:**

- `tools/golden_path.py` — End-to-end pipeline test (Ingest → Service → Data → Experience)

---

## III. Security Model — _Least Privilege_

Dragonfly enforces strict **Least Privilege** access control:

| Role            | Access                           | Use Case                              |
| --------------- | -------------------------------- | ------------------------------------- |
| `anon`          | Read-only to public views        | Frontend dashboard (Experience Plane) |
| `authenticated` | Read + limited write (RLS-gated) | Future: authenticated user actions    |
| `service_role`  | Full read/write                  | Backend workers, ETL, API mutations   |

**Security Contracts:**

1. **Frontend (Experience Plane)**

   - Uses `anon` key only
   - Cannot access `service_role` endpoints
   - All sensitive data filtered by RLS

2. **Backend (Service Plane)**

   - Uses `service_role` key
   - Key stored in environment variables, never in code
   - All writes are transactional and audited

3. **Database (Data Plane)**
   - RLS enabled on all sensitive tables
   - `SECURITY DEFINER` functions have explicit `search_path`
   - Audit triggers on critical mutations

---

## IV. Deployment Model

| Plane      | Platform       | Trigger                                      |
| ---------- | -------------- | -------------------------------------------- |
| Data       | Supabase       | `supabase db push` via `scripts/db_push.ps1` |
| Service    | Railway        | Git push to `main` (auto-deploy)             |
| Experience | Vercel         | Git push to `main` (auto-deploy)             |
| Ops        | GitHub Actions | Push/PR triggers                             |

**Atomic Deployment:**

- Each plane deploys **independently**
- Database migrations run **before** service deploys
- Frontend deploys **after** backend is healthy

---

## V. Directory Mapping

| Directory              | Plane      | Purpose                        |
| ---------------------- | ---------- | ------------------------------ |
| `supabase/`            | Data       | Migrations, schema definitions |
| `backend/`             | Service    | FastAPI application, workers   |
| `etl/`                 | Service    | Ingestion pipelines            |
| `workers/`             | Service    | Background processors          |
| `brain/`               | Service    | Scoring & escalation logic     |
| `dragonfly-dashboard/` | Experience | React frontend                 |
| `scripts/`             | Ops        | PowerShell automation          |
| `tools/`               | Ops        | Python tooling & gates         |
| `.github/workflows/`   | Ops        | CI/CD pipelines                |
| `docs/`                | Ops        | Documentation                  |

---

## VI. Principles

1. **Separation of Concerns** — Each plane owns its responsibility. No leaking.
2. **Defense in Depth** — Multiple validation layers (ETL → Service → DB constraints → RLS).
3. **Fail Safe** — Unknown states halt execution; never proceed blindly.
4. **Observable** — Every action is logged, every error is alerted.
5. **Immutable History** — Audit logs are append-only; no silent mutations.

---

_Last Updated: January 2026_
_Maintainer: Dragonfly Engineering_
