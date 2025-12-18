# Dragonfly Civil - Railway/Heroku Procfile
# ============================================================================
# RAILWAY DEPLOYMENT GUIDE:
# Each service needs its Start Command set in Railway dashboard:
#
#   dragonfly-api:              uvicorn backend.main:app --host 0.0.0.0 --port $PORT
#   dragonfly-worker-ingest:    python -m backend.workers.ingest_processor
#   dragonfly-worker-enforcement: python -m backend.workers.enforcement_engine
#
# REQUIRED ENV VARS (all services):
#   SUPABASE_URL                - https://xxx.supabase.co
#   SUPABASE_SERVICE_ROLE_KEY   - eyJ... (100+ chars)
#   SUPABASE_DB_URL             - postgresql://postgres:...@...pooler.supabase.com:5432/postgres
#   SUPABASE_MODE               - prod
#   ENVIRONMENT                 - prod
#
# ADDITIONAL (per service):
#   dragonfly-api:              DRAGONFLY_API_KEY, PORT (auto-injected by Railway)
#   dragonfly-worker-enforcement: OPENAI_API_KEY (for AI agents)
# ============================================================================

web: uvicorn backend.main:app --host 0.0.0.0 --port $PORT
ingest: python -m backend.workers.ingest_processor
enforcement: python -m backend.workers.enforcement_engine
simplicity: python -m backend.workers.simplicity_ingest_worker
