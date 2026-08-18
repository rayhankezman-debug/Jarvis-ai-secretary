"""
History and Statistics service — aggregates task progress for the user.

This service is the business logic layer for Phase 9 (History & Statistics).
It queries the database for tasks within a date range and calculates
productivity metrics such as completion rate, most productive day, etc.

Security: All queries are strictly scoped by telegram_user_id.
"""

from datetime import datetime, time
from typing import Optional
from zoneinfo import ZoneInfo
from collections import defaultdict

from sqlalchemy import select, and_, or_

from app.core.config import settings
from app.core.logging import get_logger
from app.database.models import Task, TaskStatus
from app.database.session import get_db_session

logger = get_logger(__name__)
TZ = ZoneInfo(settings.timezone)


class HistoryService:
    """
    Service for generating productivity statistics from task history.
    """

    @staticmethod
    async def get_statistics(
        telegram_user_id: int,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> dict:
        """
        Calculate task statistics for a specific user within a date range.

        Args:
            telegram_user_id: The Telegram user ID to scope the query.
            start_date: Optional ISO 8601 date string (inclusive).
            end_date: Optional ISO 8601 date string (inclusive).

        Returns:
            Dictionary with aggregated statistics.
        """
        try:
            start_dt = None
            end_dt = None

            if start_date:
                parsed = datetime.fromisoformat(start_date)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=TZ)
                start_dt = datetime.combine(parsed.date(), time.min, tzinfo=TZ)
            
            if end_date:
                parsed = datetime.fromisoformat(end_date)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=TZ)
                end_dt = datetime.combine(parsed.date(), time.max, tzinfo=TZ)
        except (ValueError, TypeError):
            return {"success": False, "error": "Format tanggal tidak valid."}

        try:
            async with get_db_session() as session:
                conditions = [Task.telegram_user_id == telegram_user_id]
                
                # If date range is provided, only include tasks relevant to that range
                if start_dt and end_dt:
                    conditions.append(
                        or_(
                            and_(Task.created_at >= start_dt, Task.created_at <= end_dt),
                            and_(Task.due_date >= start_dt, Task.due_date <= end_dt),
                            and_(Task.completed_at >= start_dt, Task.completed_at <= end_dt),
                        )
                    )
                elif start_dt:
                    conditions.append(
                        or_(
                            Task.created_at >= start_dt,
                            Task.due_date >= start_dt,
                            Task.completed_at >= start_dt,
                        )
                    )
                elif end_dt:
                    conditions.append(
                        or_(
                            Task.created_at <= end_dt,
                            Task.due_date <= end_dt,
                            Task.completed_at <= end_dt,
                        )
                    )

                query = select(Task).where(and_(*conditions))
                result = await session.execute(query)
                tasks = result.scalars().all()

                # Process tasks
                total = len(tasks)
                completed = 0
                pending = 0
                in_progress = 0
                cancelled = 0
                overdue = 0

                completed_by_day = defaultdict(int)

                now = datetime.now(TZ)

                for task in tasks:
                    status = task.status.value
                    
                    if status == TaskStatus.COMPLETED.value:
                        completed += 1
                        if task.completed_at:
                            # Convert completed_at to user's timezone for daily grouping
                            completed_date = task.completed_at.astimezone(TZ).date()
                            completed_by_day[completed_date.isoformat()] += 1
                    elif status == TaskStatus.PENDING.value:
                        pending += 1
                    elif status == TaskStatus.IN_PROGRESS.value:
                        in_progress += 1
                    elif status == TaskStatus.CANCELLED.value:
                        cancelled += 1

                    # Calculate overdue
                    if status in (TaskStatus.PENDING.value, TaskStatus.IN_PROGRESS.value):
                        if task.due_date and task.due_date < now:
                            overdue += 1

                # Calculate completion rate (ignoring cancelled tasks in the denominator)
                active_total = total - cancelled
                completion_rate = round((completed / active_total * 100)) if active_total > 0 else 0

                # Most productive day
                most_productive_day = None
                max_completed = 0
                if completed_by_day:
                    most_productive_day = max(completed_by_day.items(), key=lambda x: x[1])[0]
                    max_completed = completed_by_day[most_productive_day]

                return {
                    "success": True,
                    "date_range": {
                        "start": start_dt.isoformat() if start_dt else None,
                        "end": end_dt.isoformat() if end_dt else None,
                    },
                    "total_tasks": total,
                    "completed": completed,
                    "pending": pending,
                    "in_progress": in_progress,
                    "cancelled": cancelled,
                    "overdue": overdue,
                    "completion_rate_percent": completion_rate,
                    "most_productive_day": most_productive_day,
                    "max_completed_in_a_day": max_completed,
                    "completed_by_day": dict(completed_by_day),
                }

        except Exception as e:
            logger.error(f"Failed to get history statistics for user {telegram_user_id}: {e}")
            return {"success": False, "error": "Gagal mengambil statistik tugas."}
