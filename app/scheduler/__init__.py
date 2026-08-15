"""
Scheduler package — APScheduler-based reminder engine.

Public API:
    ReminderService   — Checks tasks and generates reminders
    ReminderType      — Enum of reminder types (H1, H0, DUE_SOON, OVERDUE)
    Reminder          — Dataclass representing a pending reminder
    SchedulerEngine   — APScheduler lifecycle and job management
    get_scheduler     — Get the scheduler singleton
    set_scheduler     — Set the scheduler singleton
    reset_scheduler   — Reset singleton (testing)
"""

from app.scheduler.reminder_service import (
    ReminderService,
    ReminderType,
    Reminder,
)
from app.scheduler.engine import (
    SchedulerEngine,
    get_scheduler,
    set_scheduler,
    reset_scheduler,
)

__all__ = [
    "ReminderService",
    "ReminderType",
    "Reminder",
    "SchedulerEngine",
    "get_scheduler",
    "set_scheduler",
    "reset_scheduler",
]
