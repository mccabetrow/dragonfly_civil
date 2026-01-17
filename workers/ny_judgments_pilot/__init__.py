"""
NY Judgments Pilot Worker

Scheduled ingestion worker for NY civil judgment data.

Run via: python -m workers.ny_judgments_pilot

Modules:
    config     - Pydantic-based configuration (DATABASE_URL, ENV only)
    scraper    - Portal scraping interface (stub until portal access)
    normalize  - Pure, deterministic record canonicalization
    db         - Database operations (psycopg3 sync)
    main       - Orchestration logic
    worker     - Legacy orchestration (deprecated)
"""

__version__ = "1.0.0"

# Export key components for external testing
from .config import WorkerConfig, load_config
from .normalize import (
    NormalizedRecord,
    compute_content_hash,
    compute_dedupe_key,
    normalize_batch,
    normalize_record,
)
from .scraper import NYSupremeCourtScraper, ScraperError, ScrapeResult, ScraperNotImplementedError

__all__ = [
    "WorkerConfig",
    "load_config",
    "NormalizedRecord",
    "compute_content_hash",
    "compute_dedupe_key",
    "normalize_batch",
    "normalize_record",
    "NYSupremeCourtScraper",
    "ScraperError",
    "ScraperNotImplementedError",
    "ScrapeResult",
]
