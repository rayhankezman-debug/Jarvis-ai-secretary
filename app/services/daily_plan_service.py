"""
Daily plan service — fetches tasks for a date and builds planner context.

This service is the data layer for the Daily Planner feature (Phase 6).
It queries the user's tasks for a requested date range and formats them
into structured context that the AI can use to generate a natural
daily plan.

Architecture:
    AI Agent → generate_daily_plan tool → DailyPlanService → Database
        → returns structured task data → AI formats into schedule

Security: All queries are scoped by telegram_user_id.
"""

from datetime import datetime, timedelta, time
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select, and_

from app.core.config import settings
from app.core.logging import get_logger
from app.database.models import Task, TaskStatus
from app.database.session import get_db_session

logger = get_logger(__name__)

TZ = ZoneInfo(settings.timezone)

# Active statuses to include in daily plans
_ACTIVE_STATUSES = {TaskStatus.PENDING, TaskStatus.IN_PROGRESS}

# Priority sort order (higher priority first)
_PRIORITY_ORDER = {"urgent": 0, "high": 1, "medium": 2, "low": 3}


class DailyPlanService:
    """
    Service for generating daily plan context from existing tasks.

    All methods are static and require telegram_user_id
    to ensure user isolation.
    """

    @staticmethod
    async def get_daily_plan(
        telegram_user_id: int,
        target_date: Optional[str] = None,
    ) -> dict:
        """
        Fetch active tasks for a given date and return structured plan data.

        If target_date is not provided, defaults to today.

        Args:
            telegram_user_id: Owner's Telegram user ID.
            target_date: ISO 8601 date string (e.g. '2026-08-18').
                         Can be a full datetime or just a date.

        Returns:
            Dict with success status, date info, and tasks organized
            for the AI to format into a daily plan.
        """
        # Parse target date
        try:
            if target_date:
                parsed = datetime.fromisoformat(target_date)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=TZ)
                plan_date = parsed.date()
            else:
                plan_date = datetime.now(TZ).date()
        except (ValueError, TypeError):
            return {
                "success": False,
                "error": f"Format tanggal tidak valid: {target_date}",
            }

        # Build date range: start of day to end of day
        day_start = datetime.combine(plan_date, time.min, tzinfo=TZ)
        day_end = datetime.combine(plan_date, time.max, tzinfo=TZ)

        # Indonesian day names
        day_names = {
            0: "Senin", 1: "Selasa", 2: "Rabu", 3: "Kamis",
            4: "Jumat", 5: "Sabtu", 6: "Minggu",
        }
        day_name = day_names[plan_date.weekday()]

        try:
            async with get_db_session() as session:
                # Query 1: Tasks due on the target date (active only)
                query_due = select(Task).where(
                    and_(
                        Task.telegram_user_id == telegram_user_id,
                        Task.status.in_([s.value for s in _ACTIVE_STATUSES]),
                        Task.due_date >= day_start,
                        Task.due_date <= day_end,
                    )
                ).order_by(Task.due_date.asc())

                result_due = await session.execute(query_due)
                tasks_due = result_due.scalars().all()

                # Query 2: Overdue tasks (due before today, still active)
                query_overdue = select(Task).where(
                    and_(
                        Task.telegram_user_id == telegram_user_id,
                        Task.status.in_([s.value for s in _ACTIVE_STATUSES]),
                        Task.due_date < day_start,
                        Task.due_date.isnot(None),
                    )
                ).order_by(Task.due_date.asc())

                result_overdue = await session.execute(query_overdue)
                tasks_overdue = result_overdue.scalars().all()

                # Query 3: Active tasks without due_date (backlog)
                query_backlog = select(Task).where(
                    and_(
                        Task.telegram_user_id == telegram_user_id,
                        Task.status.in_([s.value for s in _ACTIVE_STATUSES]),
                        Task.due_date.is_(None),
                    )
                ).order_by(Task.created_at.desc())

                result_backlog = await session.execute(query_backlog)
                tasks_backlog = result_backlog.scalars().all()

                # Format tasks
                scheduled = _format_tasks(tasks_due)
                overdue = _format_tasks(tasks_overdue)
                backlog = _format_tasks(tasks_backlog)

                total = len(scheduled) + len(overdue) + len(backlog)

                return {
                    "success": True,
                    "date": plan_date.isoformat(),
                    "day_name": day_name,
                    "scheduled_tasks": scheduled,
                    "scheduled_count": len(scheduled),
                    "overdue_tasks": overdue,
                    "overdue_count": len(overdue),
                    "backlog_tasks": backlog,
                    "backlog_count": len(backlog),
                    "total_tasks": total,
                    "message": (
                        f"Rencana untuk {day_name}, {plan_date.strftime('%d %B %Y')}"
                        if total > 0
                        else f"Tidak ada tugas untuk {day_name}, {plan_date.strftime('%d %B %Y')}. Hari bebas! 🎉"
                    ),
                }

        except Exception as e:
            logger.error(
                f"Failed to get daily plan for user {telegram_user_id}: {e}"
            )
            return {
                "success": False,
                "error": "Gagal membuat rencana harian. Silakan coba lagi.",
            }


def _format_tasks(tasks: list) -> list[dict]:
    """Format a list of Task model instances into serializable dicts."""
    formatted = []
    for t in tasks:
        formatted.append({
            "task_id": t.id,
            "title": t.title,
            "description": t.description,
            "due_date": t.due_date.astimezone(TZ).isoformat() if t.due_date else None,
            "priority": t.priority.value,
            "status": t.status.value,
        })
    # Sort by priority (urgent first)
    formatted.sort(key=lambda x: _PRIORITY_ORDER.get(x["priority"], 99))
    return formatted
