# Dragonfly Civil - Railway/Heroku Procfile
# Each service type has its own process target
# Railway: Set PROCFILE_TARGET env var or override Start Command in dashboard

web: uvicorn backend.main:app --host 0.0.0.0 --port $PORT
ingest: python -m backend.workers.ingest_processor
enforcement: python -m backend.workers.enforcement_engine
simplicity: python -m backend.workers.simplicity_ingest_worker
