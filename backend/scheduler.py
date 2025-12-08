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


async def daily_health_broadcast_job() -> None:
    """
    Daily job to broadcast system health to Discord.
    Runs at 5 PM Eastern to summarize the day's activity.

    This wrapper handles exceptions so the scheduler doesn't crash.
    """
    logger.info("🩺 Running daily health broadcast...")

    try:
        from .services.health_service import broadcast_daily_health

        result = await broadcast_daily_health()

        if result.get("status") == "success":
            logger.info("🩺 Daily health broadcast completed successfully")
        else:
            logger.warning(f"🩺 Daily health broadcast had issues: {result.get('error')}")

    except Exception as e:
        logger.exception(f"🩺 Daily health broadcast job failed: {e}")
        # Don't re-raise - we don't want to crash the scheduler


async def foil_followup_job() -> None:
    """
    Daily job to process FOIL follow-ups.
    Runs at 10 AM Eastern to send follow-ups for pending requests.

    This wrapper handles exceptions so the scheduler doesn't crash.
    """
    logger.info("📋 Running FOIL follow-up job...")

    try:
        from .services.foil_service import broadcast_foil_followup_result, process_foil_followups

        processed = await process_foil_followups()
        await broadcast_foil_followup_result(processed)

        logger.info(f"📋 FOIL follow-up job completed: {processed} processed")

    except Exception as e:
        logger.exception(f"📋 FOIL follow-up job failed: {e}")
        # Don't re-raise - we don't want to crash the scheduler


async def ceo_morning_briefing_job() -> None:
    """
    Daily job to send CEO morning briefing.
    Runs at 8:30 AM Eastern, Monday-Friday.

    Aggregates enforcement pipeline, offer stats, and system health
    into a concise executive summary email.
    """
    logger.info("📧 Running CEO morning briefing job...")

    try:
        from .services.notification_service import send_ceo_briefing
        from .services.reporting_service import generate_ceo_briefing

        briefing = await generate_ceo_briefing()

        result = await send_ceo_briefing(
            subject=briefing["subject"],
            html_body=briefing["html_body"],
            plain_body=briefing["plain_body"],
        )

        if result.get("success"):
            logger.info("📧 CEO morning briefing sent successfully")
        else:
            logger.warning(f"📧 CEO briefing failed: {result.get('error')}")

    except Exception as e:
        logger.exception(f"📧 CEO morning briefing job failed: {e}")
        # Don't re-raise - we don't want to crash the scheduler


async def pending_batch_processor_job() -> None:
    """
    Periodic job to process pending ingest batches.
    Runs every 5 minutes to pick up batches that weren't processed inline.

    This ensures batches uploaded with process_now=False eventually get processed,
    and provides a retry mechanism for any transient failures.

    The processing function is idempotent, so re-running is safe.
    """
    logger.info("📦 Running pending batch processor...")

    try:
        from .services.ingest_service_v2 import get_pending_batches, process_simplicity_batch
        from .services.notifications import notify_pending_batches_processed

        pending = await get_pending_batches()

        if not pending:
            logger.debug("📦 No pending batches to process")
            return

        logger.info(f"📦 Found {len(pending)} pending batches")

        success_count = 0
        failure_count = 0

        for batch_id in pending:
            try:
                result = await process_simplicity_batch(batch_id)
                if result.status == "completed":
                    success_count += 1
                else:
                    failure_count += 1
            except Exception as batch_err:
                logger.error(f"📦 Failed to process batch {batch_id}: {batch_err}")
                failure_count += 1

        # Notify if any batches were processed
        if success_count > 0 or failure_count > 0:
            await notify_pending_batches_processed(
                processed_count=len(pending),
                success_count=success_count,
                failure_count=failure_count,
            )

        logger.info(
            f"📦 Batch processor complete: {success_count} succeeded, " f"{failure_count} failed"
        )

    except Exception as e:
        logger.exception(f"📦 Pending batch processor job failed: {e}")
        # Don't re-raise - we don't want to crash the scheduler


async def intake_guardian_job() -> None:
    """
    Periodic job to detect and recover stuck intake batches.
    Runs every 60 seconds to find batches stuck in 'processing' state.

    This is a self-healing mechanism that:
    - Marks stuck batches as 'failed'
    - Logs the failure reason
    - Sends Discord alerts

    The guardian is fault-tolerant and will not crash the scheduler on errors.
    """
    logger.debug("🛡️ Running intake guardian check...")

    try:
        from .services.intake_guardian import get_intake_guardian

        guardian = get_intake_guardian()
        result = await guardian.check_stuck_batches()

        if result.marked_failed > 0:
            logger.warning(f"🛡️ Intake Guardian: Marked {result.marked_failed} batch(es) as failed")
        elif result.checked > 0:
            logger.debug(f"🛡️ Intake Guardian: Checked {result.checked} batch(es), all OK")

    except Exception as e:
        logger.exception(f"🛡️ Intake guardian job failed: {e}")
        # Don't re-raise - we don't want to crash the scheduler


async def schema_guard_job() -> None:
    """
    Schema Guard self-healing job.
    Runs every 15 minutes to detect and auto-repair schema drift.

    This is a production-critical self-healing mechanism that:
    - Detects missing views/columns (schema drift)
    - Automatically executes repair SQL files
    - Sends Discord alerts on drift detection and repair status

    The guard is fault-tolerant and will not crash the scheduler on errors.
    """
    logger.info("🛡️ Running Schema Guard check...")

    try:
        from .maintenance import check_and_repair

        result = await check_and_repair()

        if result.get("drift_detected"):
            logger.warning(
                f"🛡️ Schema Guard detected drift - repair_triggered={result.get('repair_triggered')}"
            )
        else:
            logger.debug("🛡️ Schema Guard: No drift detected, schema healthy")

        if result.get("error"):
            logger.error(f"🛡️ Schema Guard error: {result.get('error')}")

    except Exception as e:
        logger.exception(f"🛡️ Schema Guard job failed: {e}")
        # Don't re-raise - we don't want to crash the scheduler


async def daily_recap_job() -> None:
    """
    Daily "Sleep Well" recap job.
    Runs at 5 PM Eastern to summarize the day's activity.

    Sends a rich notification with:
    - New Judgments
    - Gig Hits
    - Served Papers
    - Total Portfolio Value
    """
    logger.info("🌙 Running daily recap job...")

    try:
        from .services.notification_service import send_daily_recap

        result = await send_daily_recap()

        if result.get("success"):
            stats = result.get("stats", {})
            logger.info(
                "🌙 Daily recap sent: new=%d, gig=%d, served=%d, value=$%.2f",
                stats.get("new_judgments", 0),
                stats.get("gig_hits", 0),
                stats.get("served_papers", 0),
                stats.get("portfolio_value", 0.0),
            )
        else:
            logger.warning(f"🌙 Daily recap delivery issues: {result}")

    except Exception as e:
        logger.exception(f"🌙 Daily recap job failed: {e}")
        # Don't re-raise - we don't want to crash the scheduler


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

    # Daily health broadcast - 5 PM Eastern every day
    scheduler.add_job(
        daily_health_broadcast_job,
        trigger=CronTrigger(hour=17, minute=0),
        id="daily_health_broadcast",
        name="Daily Health Broadcast",
        replace_existing=True,
    )

    # Daily recap ("Sleep Well") - 5 PM Eastern every day
    scheduler.add_job(
        daily_recap_job,
        trigger=CronTrigger(hour=17, minute=0),
        id="daily_recap",
        name="Daily Recap (Sleep Well)",
        replace_existing=True,
    )

    # FOIL follow-up - 10 AM Eastern every day
    scheduler.add_job(
        foil_followup_job,
        trigger=CronTrigger(hour=10, minute=0),
        id="foil_followup",
        name="FOIL Follow-up Processing",
        replace_existing=True,
    )

    # CEO Morning Briefing - 8:30 AM Eastern, Monday-Friday
    scheduler.add_job(
        ceo_morning_briefing_job,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=8,
            minute=30,
        ),
        id="ceo_morning_briefing",
        name="CEO Morning Briefing",
        replace_existing=True,
    )

    # Pending batch processor - every 5 minutes
    scheduler.add_job(
        pending_batch_processor_job,
        trigger=IntervalTrigger(minutes=5),
        id="pending_batch_processor",
        name="Pending Batch Processor",
        replace_existing=True,
    )

    # Intake Guardian - every 60 seconds (self-healing for stuck batches)
    scheduler.add_job(
        intake_guardian_job,
        trigger=IntervalTrigger(seconds=60),
        id="intake_guardian",
        name="Intake Guardian",
        replace_existing=True,
    )

    # Schema Guard - every 15 minutes (self-healing for schema drift)
    scheduler.add_job(
        schema_guard_job,
        trigger=IntervalTrigger(minutes=15),
        id="schema_guard",
        name="Schema Guard",
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
    result = []
    for job in scheduler.get_jobs():
        next_run = None
        if hasattr(job, "next_run_time") and job.next_run_time:
            next_run = job.next_run_time.isoformat()
        elif hasattr(job, "trigger"):
            # Try to get next fire time from trigger
            try:
                from datetime import datetime

                next_fire = job.trigger.get_next_fire_time(None, datetime.now())
                if next_fire:
                    next_run = next_fire.isoformat()
            except Exception:
                pass

        result.append(
            {
                "id": job.id,
                "name": job.name,
                "trigger": str(job.trigger),
                "next_run": next_run,
            }
        )
    return result
