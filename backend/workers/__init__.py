"""
Dragonfly Engine - Backend Workers

Background job processors for async tasks.

NOTE: Worker modules are designed to be run directly via:
    python -m backend.workers.ingest_processor
    python -m backend.workers.enforcement_engine

Do NOT import worker modules here to avoid sys.modules RuntimeWarning
when running workers as __main__.
"""

# Intentionally empty - workers are run as modules, not imported
