# ADR-001: Adoption of North Star 4-Plane Architecture

| Metadata            | Value                 |
| ------------------- | --------------------- |
| **Status**          | Accepted              |
| **Date**            | 2026-01-01            |
| **Decision Makers** | Dragonfly Engineering |
| **Supercedes**      | N/A                   |

---

## Context

Dragonfly Civil is a judgment-enforcement operating system that handles **sensitive plaintiff data** and must maintain **high availability** for legal operations. The system integrates multiple external services (Supabase, Railway, Vercel) and processes financial and personal information subject to regulatory requirements.

**Challenges identified:**

1. **Security** — Plaintiff PII requires strict access control; credentials must never leak to frontend.
2. **Reliability** — The system must gracefully handle service outages without data loss.
3. **Maintainability** — Clear boundaries needed for a growing codebase with multiple contributors.
4. **Auditability** — All mutations must be traceable for legal and compliance purposes.

**Options considered:**

| Option        | Description                         | Rejected Because                      |
| ------------- | ----------------------------------- | ------------------------------------- |
| Monolith      | Single deployable with shared state | No isolation; credential leakage risk |
| Microservices | Fine-grained service decomposition  | Over-engineering for current scale    |
| **4-Plane**   | Logical separation by concern       | ✅ Selected                           |

---

## Decision

We adopt a **4-Plane Architecture** that logically separates the system into:

| Plane                | Responsibility                                    | Technology                     |
| -------------------- | ------------------------------------------------- | ------------------------------ |
| **Data Plane**       | Source of truth, schema integrity, access control | Supabase Postgres, RLS         |
| **Service Plane**    | Business logic, mutations, scoring, ETL           | Python FastAPI, Railway        |
| **Experience Plane** | User interface, read-only data access             | React, Vercel, PostgREST       |
| **Ops Plane**        | CI/CD, monitoring, alerting, governance           | GitHub Actions, Python tooling |

**Key Architectural Decisions:**

1. **The Data Plane is authoritative** — All other planes derive state from Postgres.
2. **The Service Plane is the only writer** — Frontend never writes directly to the database.
3. **The Experience Plane is read-only** — Uses PostgREST with fallback to Service API.
4. **The Ops Plane enforces governance** — Automated gates prevent unsafe deployments.

---

## Consequences

### Positive

1. **Clear ownership** — Each plane has a defined technology stack and maintainer scope.
2. **Security by design** — Service role credentials are isolated to the Service Plane.
3. **Resilience** — Dual-source reads (PostgREST + API) enable graceful degradation.
4. **Testability** — Each plane can be validated independently (smoke tests, golden path).

### Negative

1. **Increased complexity** — Developers must understand which plane owns a feature.
2. **Dual-source logic** — Frontend must implement fallback patterns for resilience.
3. **Deployment coordination** — Database migrations must precede service deployments.

### Neutral

1. **Deployment is atomic per plane** — Each plane deploys independently via its platform.
2. **Observability is distributed** — Logs span multiple services (Supabase, Railway, Vercel).

---

## Compliance

All contributions to Dragonfly Civil must respect the 4-Plane boundaries:

| Rule                                       | Enforcement                  |
| ------------------------------------------ | ---------------------------- |
| Frontend must not hold `service_role` keys | Code review, secret scanning |
| Mutations must route through Service Plane | RLS policies, API design     |
| Schema changes require migrations          | `tools/verify_migrations.py` |
| Production deploys require gate pass       | `tools/go_live_gate.py`      |

---

## References

- [docs/ARCHITECTURE.md](../ARCHITECTURE.md) — Full architecture specification
- [tools/go_live_gate.py](../../tools/go_live_gate.py) — Production readiness gate
- [tools/golden_path.py](../../tools/golden_path.py) — End-to-end validation

---

_This ADR is immutable. Future changes require a new ADR that supercedes this one._
