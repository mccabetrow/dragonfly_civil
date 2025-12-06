# Dragonfly Civil v1.0 — Release Notes

**Release Date:** December 2025  
**Codename:** Judgment Day  
**Classification:** Production-Ready

---

## 🎯 Summary

Dragonfly Civil v1.0 is the first production release of the judgment enforcement operating system. This release delivers a fully operational platform for plaintiff intake, case enrichment, enforcement automation, and executive reporting.

---

## ✨ Major Features

### 1. Intake Gateway

- **CSV Upload Pipeline** — Simplicity and JBI vendor CSV ingestion with validation
- **Batch Processing** — Async batch processing with progress tracking
- **Enrichment Queues** — Automatic job queuing for skip-trace and entity resolution
- **Error Recovery** — Failed row export and reprocessing workflows

### 2. Enforcement Radar

- **Collectability Scoring** — Tier-based (A/B/C/D) scoring with multi-factor analysis
- **Priority Pipeline** — Real-time prioritized view of enforcement opportunities
- **Case Detail Drawer** — Tabbed interface with Scorecard, Intelligence, and Offers tabs
- **Offer Engine** — Purchase and contingency offer recording with cents-on-dollar calculations

### 3. Executive Dashboard

- **KPI Strip** — Real-time metrics: Total Pipeline, Avg Score, Pending Offers
- **Plaintiff Call Queue** — Prioritized outreach list with contact history
- **Activity Stream** — Live event timeline for all system actions

### 4. Backend API

- **FastAPI + Uvicorn** — High-performance async Python backend
- **Supabase/PostgreSQL** — Enterprise-grade database with RLS security
- **CORS Support** — Full Vercel preview deployment compatibility
- **API Key Authentication** — X-DRAGONFLY-API-KEY header auth

### 5. Compliance

- **FCRA Audit Logging** — All sensitive data access logged
- **FDCPA Contact Guards** — Time-of-day and frequency limits enforced
- **RLS Policies** — Row-level security on all tables
- **Delete Blocking Triggers** — FCRA-protected tables prevent accidental deletion

---

## 🔧 Technical Improvements

### Windows Compatibility

- Added `backend/asyncio_compat.py` to fix psycopg3 + Windows ProactorEventLoop incompatibility
- Event loop policy set before any imports in `main.py` and `db.py`

### CORS Configuration

- `cors_origin_regex` property for Vercel preview deployments
- `allow_credentials=True` for cross-origin auth headers
- Full test coverage for production origins

### Error Handling

- Standardized `ErrorResponse` format across all endpoints
- Request ID correlation for debugging
- Graceful 503 responses when database unavailable

### Frontend

- `apiClient.ts` unified API client with typed errors
- `SystemDiagnostic.tsx` live backend health indicator
- `MetricsGate` component for loading/error/demo states
- `ApiErrorBanner` for contextual error guidance

---

## 📦 Database Migrations

**Total Migrations:** 180+  
**Schema Version:** 20251215000000

Key migrations:

- `0200_core_judgment_schema.sql` — Core judgment/debtor/asset tables
- `0201_fcra_audit_log.sql` — Compliance audit trail
- `0300_rls_role_mapping.sql` — Role-based access control
- `20251205000000_dragonfly_brain.sql` — Intelligence engine
- `20251206002000_offer_engine.sql` — Offer management

---

## 🧪 Testing

- **Backend:** 30+ pytest tests covering API auth, intake, offers, pipeline
- **Frontend:** Vitest component tests for IntakeUpload
- **Integration:** Full CORS and health check verification
- **Pre-commit Hooks:** black, ruff, isort, mypy, prettier, sqlfluff

---

## 🚀 Deployment

### Railway (Backend)

- Auto-deploy from `main` branch
- Environment variables: `SUPABASE_*`, `DRAGONFLY_*`, `ENVIRONMENT=prod`
- Health check: `GET /api/health`

### Vercel (Frontend)

- Auto-deploy from `main` branch
- Environment variables: `VITE_API_BASE_URL`, `VITE_DRAGONFLY_API_KEY`
- Build command: `npm run build`

### Supabase (Database)

- Push migrations: `./scripts/db_push.ps1 -SupabaseEnv prod`
- Schema reload: `python -m tools.pgrst_reload`
- Health check: `python -m tools.doctor --env prod`

---

## 📋 Known Limitations

1. **Demo Mode** — When `ENVIRONMENT=demo`, some features are locked
2. **Mypy Warnings** — Some legacy ETL modules have type annotation gaps
3. **Rate Limiting** — Only enabled in production environment

---

## 🔜 Roadmap (v1.1)

- [ ] Bulk offer submission
- [ ] DocuSign integration
- [ ] SMS/Email notifications
- [ ] Advanced analytics dashboards
- [ ] Mobile-responsive radar

---

## 📞 Support

- **Engineering:** Submit a PR or issue to `dragonfly_civil`
- **Operations:** See `docs/operations/SOP_BUNDLE.md`
- **Escalation:** Contact Engineering via Slack `#dragonfly-ops`

---

_Built with ❤️ by the Dragonfly Civil Engineering Team_
