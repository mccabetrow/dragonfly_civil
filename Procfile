# Railway Procfile - Define service start commands
# ═══════════════════════════════════════════════════════════════════════════
# Each line defines a separate service. Use different files or Railway config
# to specify which service runs on each Railway instance.

# Service 1: Backend API (main web service)
web: uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8888}

# Service 2: Ingest Processor Worker (background job processor for CSV uploads)
# Run as separate Railway service with: python -m backend.workers.ingest_processor
ingest: python -m backend.workers.ingest_processor

# Service 3: Enforcement Engine Worker (generates enforcement plans & packets)
# Run as separate Railway service with: python -m backend.workers.enforcement_engine
enforcement: python -m backend.workers.enforcement_engine
