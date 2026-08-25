"""
Task management service — the controlled interface between AI and database.

Security principle: Every operation is scoped by telegram_user_id.
The AI agent calls these functions through tool definitions;
it NEVER has direct database access.

Architecture:
    AI Agent → Tool Definitions → TaskService → Database
    (no shortcut paths allowed)
"""

from datetime import datetime, date, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select, and_, or_

from app.core.config import settings
from app.core.logging import get_logger
from app.database.models import Task, TaskStatus, TaskPriority
from app.database.session import get_db_session

logger = get_logger(__name__)

# Timezone for date calculations
TZ = ZoneInfo(settings.timezone)


class TaskService:
    """
    Service layer for task CRUD operations.

    All methods are static and require telegram_user_id.
    This ensures user isolation at the service level.
    """

    @staticmethod
    async def create_task(
        telegram_user_id: int,
        title: str,
        description: Optional[str] = None,
        due_date: Optional[str] = None,
        priority: str = "medium",
    ) -> dict:
        """
        Create a new task for the specified user.

        Args:
            telegram_user_id: Owner's Telegram user ID.
            title: Task title (required, non-empty).
            description: Optional longer description.
            due_date: ISO 8601 datetime string (optional).
            priority: One of low/medium/high/urgent.

        Returns:
            Dict with success status and task details or error.
        """
        # Validate title
        if not title or not title.strip():
            return {"success": False, "error": "Judul tugas tidak boleh kosong."}

        title = title.strip()
        if len(title) > 500:
            return {"success": False, "error": "Judul tugas terlalu panjang (maks 500 karakter)."}

        # Parse due_date
        parsed_due_date = None
        if due_date:
            try:
                parsed_due_date = datetime.fromisoformat(due_date)
                # Ensure timezone-aware
                if parsed_due_date.tzinfo is None:
                    parsed_due_date = parsed_due_date.replace(tzinfo=TZ)
            except (ValueError, TypeError):
                return {"success": False, "error": f"Format tanggal tidak valid: {due_date}"}

        # Parse priority
        try:
            task_priority = TaskPriority(priority.lower())
        except ValueError:
            task_priority = TaskPriority.MEDIUM

        try:
            async with get_db_session() as session:
                task = Task(
                    telegram_user_id=telegram_user_id,
                    title=title,
                    description=description.strip() if description else None,
                    due_date=parsed_due_date,
                    priority=task_priority,
                    status=TaskStatus.PENDING,
                )
                session.add(task)
                await session.flush()

                result = {
                    "success": True,
                    "task_id": task.id,
                    "title": task.title,
                    "description": task.description,
                    "due_date": task.due_date.astimezone(TZ).isoformat() if task.due_date else None,
                    "priority": task.priority.value,
                    "status": task.status.value,
                }

            logger.info(f"Task created: id={result['task_id']} for user {telegram_user_id}")
            return result

        except Exception as e:
            logger.error(f"Failed to create task for user {telegram_user_id}: {e}")
            return {"success": False, "error": "Gagal membuat tugas. Silakan coba lagi."}

    @staticmethod
    async def list_tasks(
        telegram_user_id: int,
        status: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        title_search: Optional[str] = None,
    ) -> dict:
        """
        List tasks for the specified user with optional filters.

        Args:
            telegram_user_id: Owner's Telegram user ID.
            status: Filter by status (pending/in_progress/completed/cancelled).
            date_from: ISO 8601 date string — tasks due on or after this date.
            date_to: ISO 8601 date string — tasks due on or before this date.
            title_search: Search tasks by title (case-insensitive substring).

        Returns:
            Dict with success status and list of tasks.
        """
        try:
            async with get_db_session() as session:
                query = select(Task).where(Task.telegram_user_id == telegram_user_id)

                # Status filter
                if status:
                    try:
                        task_status = TaskStatus(status.lower())
                        query = query.where(Task.status == task_status)
                    except ValueError:
                        pass  # Ignore invalid status filter

                # Date range filters
                if date_from:
                    try:
                        dt_from = datetime.fromisoformat(date_from)
                        if dt_from.tzinfo is None:
                            dt_from = dt_from.replace(tzinfo=TZ)
                        query = query.where(Task.due_date >= dt_from)
                    except (ValueError, TypeError):
                        pass

                if date_to:
                    try:
                        dt_to = datetime.fromisoformat(date_to)
                        if dt_to.tzinfo is None:
                            dt_to = dt_to.replace(tzinfo=TZ)
                        query = query.where(Task.due_date <= dt_to)
                    except (ValueError, TypeError):
                        pass

                # Title search
                if title_search:
                    query = query.where(Task.title.ilike(f"%{title_search}%"))

                # Order by due_date (soonest first), then by created_at
                query = query.order_by(
                    Task.due_date.asc().nullslast(),
                    Task.created_at.desc(),
                )

                result = await session.execute(query)
                tasks = result.scalars().all()

                task_list = []
                for t in tasks:
                    task_list.append({
                        "task_id": t.id,
                        "title": t.title,
                        "description": t.description,
                        "due_date": t.due_date.astimezone(TZ).isoformat() if t.due_date else None,
                        "priority": t.priority.value,
                        "status": t.status.value,
                        "completed_at": t.completed_at.astimezone(TZ).isoformat() if t.completed_at else None,
                        "created_at": t.created_at.astimezone(TZ).isoformat() if t.created_at else None,
                    })

                return {"success": True, "tasks": task_list, "count": len(task_list)}

        except Exception as e:
            logger.error(f"Failed to list tasks for user {telegram_user_id}: {e}")
            return {"success": False, "error": "Gagal mengambil daftar tugas.", "tasks": [], "count": 0}

    @staticmethod
    async def update_task(
        telegram_user_id: int,
        task_id: int,
        title: Optional[str] = None,
        description: Optional[str] = None,
        due_date: Optional[str] = None,
        priority: Optional[str] = None,
    ) -> dict:
        """
        Update an existing task. Only provided fields are changed.

        Args:
            telegram_user_id: Owner's Telegram user ID (for ownership check).
            task_id: ID of the task to update.
            title: New title (optional).
            description: New description (optional).
            due_date: New due date as ISO 8601 string (optional).
            priority: New priority (optional).

        Returns:
            Dict with success status and updated task details.
        """
        if not task_id:
            return {"success": False, "error": "Task ID diperlukan."}

        try:
            async with get_db_session() as session:
                result = await session.execute(
                    select(Task).where(
                        and_(Task.id == task_id, Task.telegram_user_id == telegram_user_id)
                    )
                )
                task = result.scalar_one_or_none()

                if task is None:
                    return {"success": False, "error": f"Tugas dengan ID {task_id} tidak ditemukan."}

                # Apply updates
                if title is not None:
                    cleaned = title.strip()
                    if not cleaned:
                        return {"success": False, "error": "Judul tugas tidak boleh kosong."}
                    task.title = cleaned

                if description is not None:
                    task.description = description.strip() if description else None

                if due_date is not None:
                    try:
                        parsed = datetime.fromisoformat(due_date)
                        if parsed.tzinfo is None:
                            parsed = parsed.replace(tzinfo=TZ)
                        task.due_date = parsed
                    except (ValueError, TypeError):
                        return {"success": False, "error": f"Format tanggal tidak valid: {due_date}"}

                if priority is not None:
                    try:
                        task.priority = TaskPriority(priority.lower())
                    except ValueError:
                        pass  # Keep existing priority if invalid

                await session.flush()

                updated = {
                    "success": True,
                    "task_id": task.id,
                    "title": task.title,
                    "description": task.description,
                    "due_date": task.due_date.astimezone(TZ).isoformat() if task.due_date else None,
                    "priority": task.priority.value,
                    "status": task.status.value,
                }

            logger.info(f"Task updated: id={task_id} for user {telegram_user_id}")
            return updated

        except Exception as e:
            logger.error(f"Failed to update task {task_id} for user {telegram_user_id}: {e}")
            return {"success": False, "error": "Gagal mengupdate tugas. Silakan coba lagi."}

    @staticmethod
    async def complete_task(
        telegram_user_id: int,
        task_id: int,
    ) -> dict:
        """
        Mark a task as completed.

        Args:
            telegram_user_id: Owner's Telegram user ID.
            task_id: ID of the task to complete.

        Returns:
            Dict with success status.
        """
        if not task_id:
            return {"success": False, "error": "Task ID diperlukan."}

        try:
            async with get_db_session() as session:
                result = await session.execute(
                    select(Task).where(
                        and_(Task.id == task_id, Task.telegram_user_id == telegram_user_id)
                    )
                )
                task = result.scalar_one_or_none()

                if task is None:
                    return {"success": False, "error": f"Tugas dengan ID {task_id} tidak ditemukan."}

                if task.status == TaskStatus.COMPLETED:
                    return {"success": False, "error": "Tugas ini sudah diselesaikan sebelumnya."}

                if task.status == TaskStatus.CANCELLED:
                    return {"success": False, "error": "Tugas yang dibatalkan tidak bisa diselesaikan."}

                task.status = TaskStatus.COMPLETED
                task.completed_at = datetime.now(tz=ZoneInfo("UTC"))

                await session.flush()

                return {
                    "success": True,
                    "task_id": task.id,
                    "title": task.title,
                    "status": task.status.value,
                    "completed_at": task.completed_at.astimezone(TZ).isoformat(),
                }

        except Exception as e:
            logger.error(f"Failed to complete task {task_id} for user {telegram_user_id}: {e}")
            return {"success": False, "error": "Gagal menyelesaikan tugas. Silakan coba lagi."}

    @staticmethod
    async def cancel_task(
        telegram_user_id: int,
        task_id: int,
    ) -> dict:
        """
        Cancel a task.

        Args:
            telegram_user_id: Owner's Telegram user ID.
            task_id: ID of the task to cancel.

        Returns:
            Dict with success status.
        """
        if not task_id:
            return {"success": False, "error": "Task ID diperlukan."}

        try:
            async with get_db_session() as session:
                result = await session.execute(
                    select(Task).where(
                        and_(Task.id == task_id, Task.telegram_user_id == telegram_user_id)
                    )
                )
                task = result.scalar_one_or_none()

                if task is None:
                    return {"success": False, "error": f"Tugas dengan ID {task_id} tidak ditemukan."}

                if task.status == TaskStatus.CANCELLED:
                    return {"success": False, "error": "Tugas ini sudah dibatalkan sebelumnya."}

                if task.status == TaskStatus.COMPLETED:
                    return {"success": False, "error": "Tugas yang sudah selesai tidak bisa dibatalkan."}

                task.status = TaskStatus.CANCELLED

                await session.flush()

                return {
                    "success": True,
                    "task_id": task.id,
                    "title": task.title,
                    "status": task.status.value,
                }

        except Exception as e:
            logger.error(f"Failed to cancel task {task_id} for user {telegram_user_id}: {e}")
            return {"success": False, "error": "Gagal membatalkan tugas. Silakan coba lagi."}
