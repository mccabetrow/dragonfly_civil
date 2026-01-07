#!/usr/bin/env python3
"""
Dragonfly Engine - Test Worker (Heartbeat Verification)

Minimal worker to verify the BaseWorker heartbeat infrastructure.
Runs for 90 seconds, sending heartbeats every 30 seconds.

Usage:
    python -m backend.workers.test_heartbeat

Expected behavior:
    1. Worker starts, registers in workers.heartbeats
    2. Heartbeat updates every 30 seconds
    3. Status: starting -> healthy -> draining -> stopped
    4. Check: SELECT * FROM workers.heartbeats;
"""

from __future__ import annotations

import logging
import os
import sys
import time
from typing import Any

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from backend.workers.base import BaseWorker
from backend.workers.envelope import JobEnvelope

logger = logging.getLogger(__name__)


class TestHeartbeatWorker(BaseWorker):
    """Minimal worker for testing heartbeat infrastructure."""

    queue_name = "q_test_heartbeat"
    batch_size = 1
    poll_interval = 5.0  # 5 seconds between polls
    heartbeat_interval = 10  # 10 seconds for faster testing

    def process(self, envelope: JobEnvelope) -> dict[str, Any] | None:
        """Process a test job (just log it)."""
        logger.info(
            "Processing test job: entity_type=%s entity_id=%s",
            envelope.entity_type,
            envelope.entity_id,
        )
        # Simulate work
        time.sleep(1)
        return {"status": "processed", "entity_id": envelope.entity_id}


def main() -> int:
    """Run the test heartbeat worker."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )

    logger.info("=" * 60)
    logger.info("  TEST HEARTBEAT WORKER")
    logger.info("  This worker will run for ~90 seconds")
    logger.info("  Check workers.heartbeats table for updates")
    logger.info("=" * 60)

    worker = TestHeartbeatWorker()

    # Override to run for limited time instead of forever
    import signal
    import threading

    def stop_after_delay():
        time.sleep(90)  # Run for 90 seconds
        logger.info("Test duration complete, stopping worker...")
        worker._shutdown_requested = True

    # Start timeout thread
    timeout_thread = threading.Thread(target=stop_after_delay, daemon=True)
    timeout_thread.start()

    return worker.run()


if __name__ == "__main__":
    sys.exit(main())
