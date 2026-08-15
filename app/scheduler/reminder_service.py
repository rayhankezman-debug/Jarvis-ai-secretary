"""
Reminder service — checks for upcoming tasks and generates reminders.

The reminder service is the brain of the scheduling system. It:
1. Queries all active tasks with upcoming due_dates
2. Determines which reminder type(s) to send per task
3. Tracks sent reminders to avoid duplicates
4. Returns structured reminder data for the notification layer

Reminder types:
- H-1 (1 day before): "Besok kamu punya tugas: ..."
- H-0 (same day morning): "Hari ini kamu punya tugas: ..."
- DUE_SOON (30 min before): "Tugas segera: ..."
- OVERDUE (past due): "Tugas sudah lewat deadline: ..."

Architecture:
    Scheduler tick → ReminderService.check_reminders()
        → query DB for active tasks with due_date
        → determine which reminders to send
        → return list of Reminder objects
        → notification layer sends via Telegram
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select, and_

from app.core.config import settings
from app.core.logging import get_logger
from app.database.models import Task, TaskStatus
from app.database.session import get_db_session

logger = get_logger(__name__)

TZ = ZoneInfo(settings.timezone)


class ReminderType(str, Enum):
    """Types of reminders that can be sent."""
    H1 = "h1"            # 1 day before (24h-18h before due)
    H0 = "h0"            # Same day morning (due date day)
    DUE_SOON = "due_soon" # 30 minutes before
    OVERDUE = "overdue"   # Past due date


@dataclass
class Reminder:
    """A reminder to be sent to a user."""
    telegram_user_id: int
    task_id: int
    task_title: str
    task_due_date: datetime
    reminder_type: ReminderType
    message: str


# Active task statuses that should receive reminders
_ACTIVE_STATUSES = {TaskStatus.PENDING, TaskStatus.IN_PROGRESS}


class ReminderService:
    """
    Service that checks for upcoming tasks and generates reminders.

    Maintains an in-memory set of sent reminders (task_id, reminder_type)
    to avoid duplicate notifications. This set is reset on application
    restart, which is acceptable for the MVP — worst case, a reminder
    is sent again after restart.
    """

    def __init__(self):
        # Set of (task_id, reminder_type) that have already been sent
        self._sent: set[tuple[int, str]] = set()

    def has_been_sent(self, task_id: int, reminder_type: ReminderType) -> bool:
        """Check if a reminder has already been sent."""
        return (task_id, reminder_type.value) in self._sent

    def mark_sent(self, task_id: int, reminder_type: ReminderType) -> None:
        """Mark a reminder as sent to avoid duplicates."""
        self._sent.add((task_id, reminder_type.value))

    def clear_sent(self) -> None:
        """Clear all sent tracking. Used for testing."""
        self._sent.clear()

    def cleanup_completed_tasks(self, completed_task_ids: set[int]) -> None:
        """Remove sent tracking for completed/cancelled tasks to free memory."""
        self._sent = {
            (tid, rtype) for tid, rtype in self._sent
            if tid not in completed_task_ids
        }

    async def check_reminders(self) -> list[Reminder]:
        """
        Check all active tasks and generate reminders for upcoming ones.

        Returns a list of Reminder objects that should be sent.
        Already-sent reminders are excluded.

        Returns:
            List of Reminder objects to send.
        """
        now = datetime.now(TZ)
        reminders: list[Reminder] = []

        try:
            async with get_db_session() as session:
                # Query active tasks with due_date set
                query = select(Task).where(
                    and_(
                        Task.due_date.isnot(None),
                        Task.status.in_([s.value for s in _ACTIVE_STATUSES]),
                    )
                ).order_by(Task.due_date.asc())

                result = await session.execute(query)
                tasks = result.scalars().all()

                for task in tasks:
                    task_reminders = self._evaluate_task(task, now)
                    reminders.extend(task_reminders)

        except Exception as e:
            logger.error(f"Failed to check reminders: {e}")

        return reminders

    def _evaluate_task(self, task: Task, now: datetime) -> list[Reminder]:
        """
        Evaluate a single task and return any due reminders.

        Args:
            task: Task to evaluate.
            now: Current time (timezone-aware).

        Returns:
            List of Reminder objects for this task.
        """
        reminders: list[Reminder] = []
        due = task.due_date

        # Ensure due_date is timezone-aware
        if due.tzinfo is None:
            due = due.replace(tzinfo=TZ)

        time_until_due = due - now
        hours_until_due = time_until_due.total_seconds() / 3600

        # OVERDUE: past due date
        if hours_until_due < 0:
            if not self.has_been_sent(task.id, ReminderType.OVERDUE):
                reminders.append(self._make_reminder(
                    task, due, ReminderType.OVERDUE,
                    f"⚠️ Tugas sudah lewat deadline!\n\n"
                    f"📋 *{task.title}*\n"
                    f"📅 Due: {due.strftime('%d %b %Y %H:%M')} WIB\n\n"
                    f"Segera selesaikan atau perbarui jadwalnya."
                ))

        # DUE_SOON: within 30 minutes
        elif hours_until_due <= 0.5:
            if not self.has_been_sent(task.id, ReminderType.DUE_SOON):
                minutes = max(1, int(time_until_due.total_seconds() / 60))
                reminders.append(self._make_reminder(
                    task, due, ReminderType.DUE_SOON,
                    f"🔔 Tugas segera!\n\n"
                    f"📋 *{task.title}*\n"
                    f"⏰ {minutes} menit lagi ({due.strftime('%H:%M')} WIB)\n\n"
                    f"Siap-siap ya!"
                ))

        # H-0: same day (within 24 hours, but more than 30 min)
        elif hours_until_due <= 24:
            if not self.has_been_sent(task.id, ReminderType.H0):
                reminders.append(self._make_reminder(
                    task, due, ReminderType.H0,
                    f"📅 Reminder hari ini!\n\n"
                    f"📋 *{task.title}*\n"
                    f"⏰ Jam {due.strftime('%H:%M')} WIB\n\n"
                    f"Jangan lupa ya!"
                ))

        # H-1: tomorrow (24-48 hours before)
        elif hours_until_due <= 48:
            if not self.has_been_sent(task.id, ReminderType.H1):
                reminders.append(self._make_reminder(
                    task, due, ReminderType.H1,
                    f"📢 Reminder besok!\n\n"
                    f"📋 *{task.title}*\n"
                    f"📅 {due.strftime('%d %b %Y')} jam {due.strftime('%H:%M')} WIB\n\n"
                    f"Persiapkan dari sekarang 💪"
                ))

        return reminders

    def _make_reminder(
        self,
        task: Task,
        due: datetime,
        reminder_type: ReminderType,
        message: str,
    ) -> Reminder:
        """Create a Reminder object from task data."""
        return Reminder(
            telegram_user_id=task.telegram_user_id,
            task_id=task.id,
            task_title=task.title,
            task_due_date=due,
            reminder_type=reminder_type,
            message=message,
        )
