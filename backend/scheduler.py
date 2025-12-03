"""
Dragonfly Engine - Job Scheduler

APScheduler AsyncIOScheduler for background tasks.
Jobs are registered and started on FastAPI startup.
"""

import logging
from datetime import datetime
from typing import Any, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI

from .config import get_settings
from .services.discord_service import send_discord_message

logger = logging.getLogger(__name__)

# Global scheduler instance
_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    """
    Get the scheduler instance.

    Raises:
        RuntimeError: If scheduler not initialized
    """
    if _scheduler is None:
        raise RuntimeError("Scheduler not initialized. Call init_scheduler() first.")
    return _scheduler


# =============================================================================
# Built-in Jobs
# =============================================================================


async def heartbeat_job() -> None:
    """
    Heartbeat job that runs every 5 minutes.
    Logs a message and optionally pings Discord.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    logger.info(f"💓 Heartbeat: Dragonfly Engine alive at {now}")

    # In production, optionally notify Discord on startup (not every heartbeat)
    # This is just a placeholder - real jobs would do actual work


async def daily_budget_snapshot_job() -> None:
    """
    Daily job to snapshot litigation budget.
    Runs at 6 AM to prepare budget for CEO review.

    TODO: Implement actual budget calculation
    """
    logger.info("📊 Running daily budget snapshot...")

    try:
        # Import here to avoid circular imports
        from .db import supabase_rpc

        # Get current budget
        budget = await supabase_rpc("get_litigation_budget")

        if budget:
            total = budget.get("budgets", {}).get("total_daily", 0)
            logger.info(f"📊 Daily budget computed: ${total:,.2f}")

            # Notify Discord if configured
            settings = get_settings()
            if settings.discord_webhook_url:
                await send_discord_message(
                    f"📊 **Daily Budget Ready**\n"
                    f"Total Daily Budget: **${total:,.2f}**\n"
                    f"Ready for CEO approval."
                )
    except Exception as e:
        logger.error(f"Failed to compute daily budget: {e}")


async def enforcement_check_job() -> None:
    """
    Periodic job to check enforcement action statuses.
    Runs every 30 minutes during business hours.

    TODO: Implement actual enforcement checking
    """
    logger.info("⚖️ Checking enforcement action statuses...")
    # Placeholder - will query enforcement_actions table


# =============================================================================
# Scheduler Initialization
# =============================================================================


def init_scheduler(app: FastAPI) -> AsyncIOScheduler:
    """
    Initialize the APScheduler and register jobs.

    Args:
        app: FastAPI application instance

    Returns:
        The configured scheduler
    """
    global _scheduler

    settings = get_settings()

    logger.info("Initializing job scheduler...")

    _scheduler = AsyncIOScheduler(
        timezone="America/New_York",  # Eastern time for business operations
        job_defaults={
            "coalesce": True,  # Combine missed runs into one
            "max_instances": 1,  # Only one instance of each job at a time
            "misfire_grace_time": 300,  # 5 minute grace period
        },
    )

    # Register jobs
    _register_jobs(_scheduler, settings)

    # Wire up lifecycle events
    @app.on_event("startup")
    async def start_scheduler() -> None:
        logger.info("Starting job scheduler...")
        _scheduler.start()
        logger.info("Job scheduler started")

        # Log registered jobs
        jobs = _scheduler.get_jobs()
        if jobs:
            logger.info(f"Registered {len(jobs)} scheduled jobs:")
            for job in jobs:
                logger.info(f"  - {job.id}: {job.trigger}")

    @app.on_event("shutdown")
    async def stop_scheduler() -> None:
        logger.info("Stopping job scheduler...")
        _scheduler.shutdown(wait=False)
        logger.info("Job scheduler stopped")

    return _scheduler


def _register_jobs(scheduler: AsyncIOScheduler, settings: Any) -> None:
    """
    Register all scheduled jobs.
    """
    # Heartbeat - every 5 minutes
    scheduler.add_job(
        heartbeat_job,
        trigger=IntervalTrigger(minutes=5),
        id="heartbeat",
        name="Heartbeat Check",
        replace_existing=True,
    )

    # Daily budget snapshot - 6 AM Eastern
    scheduler.add_job(
        daily_budget_snapshot_job,
        trigger=CronTrigger(hour=6, minute=0),
        id="daily_budget_snapshot",
        name="Daily Budget Snapshot",
        replace_existing=True,
    )

    # Enforcement check - every 30 minutes, 8 AM - 6 PM weekdays
    scheduler.add_job(
        enforcement_check_job,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="8-18",
            minute="*/30",
        ),
        id="enforcement_check",
        name="Enforcement Status Check",
        replace_existing=True,
    )

    logger.info("Registered scheduled jobs")


def add_job(
    func: Callable,
    trigger: str | IntervalTrigger | CronTrigger,
    job_id: str,
    **kwargs: Any,
) -> None:
    """
    Add a job to the scheduler at runtime.

    Args:
        func: The async function to run
        trigger: Trigger type or instance
        job_id: Unique job identifier
        **kwargs: Additional job options
    """
    scheduler = get_scheduler()
    scheduler.add_job(func, trigger=trigger, id=job_id, replace_existing=True, **kwargs)
    logger.info(f"Added job: {job_id}")


def remove_job(job_id: str) -> None:
    """
    Remove a job from the scheduler.
    """
    scheduler = get_scheduler()
    scheduler.remove_job(job_id)
    logger.info(f"Removed job: {job_id}")


def list_jobs() -> list[dict[str, Any]]:
    """
    List all scheduled jobs.

    Returns:
        List of job info dicts
    """
    scheduler = get_scheduler()
    return [
        {
            "id": job.id,
            "name": job.name,
            "trigger": str(job.trigger),
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
        }
        for job in scheduler.get_jobs()
    ]
