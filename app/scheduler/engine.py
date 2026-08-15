"""
Scheduler engine — APScheduler setup and lifecycle management.

This module provides:
- SchedulerEngine: Manages APScheduler instance, job registration, lifecycle
- _reminder_tick: The periodic job that checks and sends reminders

Architecture:
    FastAPI lifespan → SchedulerEngine.start()
        → APScheduler runs _reminder_tick every N minutes
        → ReminderService.check_reminders() returns pending reminders
        → Telegram bot sends notification messages
        → ReminderService.mark_sent() prevents duplicates

APScheduler 3.x is used in async mode with AsyncIOScheduler.
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import settings
from app.core.logging import get_logger
from app.scheduler.reminder_service import ReminderService

logger = get_logger(__name__)

# Default check interval (in minutes)
DEFAULT_CHECK_INTERVAL_MINUTES = 5


class SchedulerEngine:
    """
    Manages the APScheduler lifecycle and reminder jobs.

    Usage:
        engine = SchedulerEngine(bot_application=bot_app)
        await engine.start()
        ...
        await engine.stop()
    """

    def __init__(
        self,
        bot_application=None,
        check_interval_minutes: int = DEFAULT_CHECK_INTERVAL_MINUTES,
    ):
        """
        Initialize the scheduler engine.

        Args:
            bot_application: The python-telegram-bot Application instance.
                Used to send reminder messages. If None, reminders are
                generated but not sent (useful for testing).
            check_interval_minutes: How often to check for reminders.
        """
        self._bot = bot_application
        self._check_interval = check_interval_minutes
        self._reminder_service = ReminderService()
        self._scheduler = AsyncIOScheduler(timezone=settings.timezone)
        self._running = False

    @property
    def running(self) -> bool:
        """Whether the scheduler is currently running."""
        return self._running

    @property
    def reminder_service(self) -> ReminderService:
        """Access the reminder service (for testing)."""
        return self._reminder_service

    async def start(self) -> None:
        """
        Start the scheduler and register the reminder check job.
        """
        if self._running:
            logger.warning("Scheduler already running")
            return

        # Register the periodic reminder check
        self._scheduler.add_job(
            self._reminder_tick,
            trigger=IntervalTrigger(minutes=self._check_interval),
            id="reminder_check",
            name="Check and send task reminders",
            replace_existing=True,
        )

        self._scheduler.start()
        self._running = True
        logger.info(
            f"Scheduler started — checking reminders every "
            f"{self._check_interval} minutes"
        )

    async def stop(self) -> None:
        """
        Stop the scheduler gracefully.
        """
        if not self._running:
            return

        self._scheduler.shutdown(wait=False)
        self._running = False
        logger.info("Scheduler stopped")

    async def _reminder_tick(self) -> None:
        """
        Periodic job: check for reminders and send notifications.

        This is called by APScheduler on the configured interval.
        """
        try:
            reminders = await self._reminder_service.check_reminders()

            if not reminders:
                return

            logger.info(f"Found {len(reminders)} reminder(s) to send")

            for reminder in reminders:
                sent = await self._send_reminder(reminder)
                if sent:
                    self._reminder_service.mark_sent(
                        reminder.task_id, reminder.reminder_type
                    )

        except Exception as e:
            logger.error(f"Reminder tick failed: {e}")

    async def _send_reminder(self, reminder) -> bool:
        """
        Send a reminder notification via Telegram.

        Args:
            reminder: Reminder object to send.

        Returns:
            True if the message was sent successfully.
        """
        if self._bot is None:
            logger.warning(
                f"No bot configured — skipping reminder for "
                f"task {reminder.task_id} ({reminder.reminder_type.value})"
            )
            return False

        try:
            await self._bot.bot.send_message(
                chat_id=reminder.telegram_user_id,
                text=reminder.message,
                parse_mode="Markdown",
            )
            logger.info(
                f"Reminder sent: task={reminder.task_id} "
                f"type={reminder.reminder_type.value} "
                f"user={reminder.telegram_user_id}"
            )
            return True
        except Exception as e:
            logger.error(
                f"Failed to send reminder for task {reminder.task_id} "
                f"to user {reminder.telegram_user_id}: {e}"
            )
            return False

    async def trigger_check(self) -> list:
        """
        Manually trigger a reminder check. Useful for testing.

        Returns:
            List of reminders found (and sent, if bot is configured).
        """
        reminders = await self._reminder_service.check_reminders()

        for reminder in reminders:
            sent = await self._send_reminder(reminder)
            if sent:
                self._reminder_service.mark_sent(
                    reminder.task_id, reminder.reminder_type
                )

        return reminders


# ──────────────────────────────────────────────
# Singleton management
# ──────────────────────────────────────────────

_engine_instance: SchedulerEngine | None = None


def get_scheduler() -> SchedulerEngine | None:
    """Get the scheduler engine singleton."""
    return _engine_instance


def set_scheduler(engine: SchedulerEngine) -> None:
    """Set the scheduler engine singleton."""
    global _engine_instance
    _engine_instance = engine


def reset_scheduler() -> None:
    """Reset the scheduler singleton. Used in testing."""
    global _engine_instance
    _engine_instance = None
