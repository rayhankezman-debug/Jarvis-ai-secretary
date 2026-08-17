"""
Evening review service — generates and delivers proactive evening summaries.

This service is the business logic layer for Phase 8 (Evening Review).
It:
1. Queries distinct Telegram user IDs from the database.
2. Fetches task progress for each user (completed today, pending today, in-progress, overdue).
3. Formats task context using Gemini (LLMProvider) and EVENING_REVIEW_PROMPT.
4. Falls back gracefully to formatted templates if AI generation fails or is unavailable.
5. Sends review messages via Telegram bot application.

Security: All user reviews are strictly isolated by telegram_user_id.
"""

import json
from datetime import datetime, time
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select, and_, or_

from app.ai.base import LLMProvider, LLMError
from app.ai.gemini import GeminiProvider
from app.ai.prompts import EVENING_REVIEW_PROMPT
from app.core.config import settings
from app.core.logging import get_logger
from app.database.models import Task, TaskStatus
from app.database.session import get_db_session

logger = get_logger(__name__)
TZ = ZoneInfo(settings.timezone)
_PRIORITY_ORDER = {"urgent": 0, "high": 1, "medium": 2, "low": 3}


class EveningReviewService:
    """
    Service for generating and dispatching daily evening reviews.
    """

    def __init__(self, llm_provider: Optional[LLMProvider] = None):
        """
        Initialize EveningReviewService.

        Args:
            llm_provider: Optional LLMProvider instance (for testing).
        """
        self._llm_provider = llm_provider

    def _get_provider(self) -> Optional[LLMProvider]:
        if self._llm_provider is not None:
            return self._llm_provider
        try:
            if settings.gemini_api_key:
                return GeminiProvider()
        except Exception as e:
            logger.warning(f"Failed to auto-initialize GeminiProvider for EveningReviewService: {e}")
        return None

    @staticmethod
    def _format_tasks(tasks: list) -> list[dict]:
        """Format a list of Task instances."""
        formatted = []
        for t in tasks:
            formatted.append({
                "task_id": t.id,
                "title": t.title,
                "due_date": t.due_date.isoformat() if t.due_date else None,
                "priority": t.priority.value,
                "status": t.status.value,
            })
        formatted.sort(key=lambda x: _PRIORITY_ORDER.get(x["priority"], 99))
        return formatted

    @staticmethod
    async def get_registered_user_ids() -> list[int]:
        """Get all distinct Telegram user IDs."""
        try:
            async with get_db_session() as session:
                query = select(Task.telegram_user_id).distinct()
                result = await session.execute(query)
                user_ids = [row[0] for row in result.all() if row[0] is not None]
                return user_ids
        except Exception as e:
            logger.error(f"Failed to query registered user IDs for evening review: {e}")
            return []

    async def get_review_data(self, telegram_user_id: int, target_date: Optional[str] = None) -> dict:
        """Fetch task progress for a specific user and date."""
        try:
            if target_date:
                parsed = datetime.fromisoformat(target_date)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=TZ)
                review_date = parsed.date()
            else:
                review_date = datetime.now(TZ).date()
        except (ValueError, TypeError):
            return {"success": False, "error": f"Format tanggal tidak valid: {target_date}"}

        day_start = datetime.combine(review_date, time.min, tzinfo=TZ)
        day_end = datetime.combine(review_date, time.max, tzinfo=TZ)

        day_names = {0: "Senin", 1: "Selasa", 2: "Rabu", 3: "Kamis", 4: "Jumat", 5: "Sabtu", 6: "Minggu"}
        day_name = day_names[review_date.weekday()]

        try:
            async with get_db_session() as session:
                # 1. Completed today
                query_completed = select(Task).where(
                    and_(
                        Task.telegram_user_id == telegram_user_id,
                        Task.status == TaskStatus.COMPLETED.value,
                        Task.completed_at >= day_start,
                        Task.completed_at <= day_end,
                    )
                ).order_by(Task.completed_at.desc())
                res_comp = await session.execute(query_completed)
                tasks_completed = res_comp.scalars().all()

                # 2. Pending today (due today, status pending)
                query_pending = select(Task).where(
                    and_(
                        Task.telegram_user_id == telegram_user_id,
                        Task.status == TaskStatus.PENDING.value,
                        Task.due_date >= day_start,
                        Task.due_date <= day_end,
                    )
                ).order_by(Task.due_date.asc())
                res_pend = await session.execute(query_pending)
                tasks_pending = res_pend.scalars().all()

                # 3. In Progress today (status in_progress AND (due today OR no due date))
                query_in_progress = select(Task).where(
                    and_(
                        Task.telegram_user_id == telegram_user_id,
                        Task.status == TaskStatus.IN_PROGRESS.value,
                        or_(Task.due_date >= day_start, Task.due_date.is_(None))
                    )
                ).order_by(Task.updated_at.desc())
                res_prog = await session.execute(query_in_progress)
                tasks_in_progress = res_prog.scalars().all()

                # 4. Overdue (due before today, status pending/in_progress)
                query_overdue = select(Task).where(
                    and_(
                        Task.telegram_user_id == telegram_user_id,
                        Task.status.in_([TaskStatus.PENDING.value, TaskStatus.IN_PROGRESS.value]),
                        Task.due_date < day_start,
                        Task.due_date.isnot(None),
                    )
                ).order_by(Task.due_date.asc())
                res_over = await session.execute(query_overdue)
                tasks_overdue = res_over.scalars().all()

                completed = self._format_tasks(tasks_completed)
                pending = self._format_tasks(tasks_pending)
                in_progress = self._format_tasks(tasks_in_progress)
                overdue = self._format_tasks(tasks_overdue)

                total = len(completed) + len(pending) + len(in_progress) + len(overdue)

                return {
                    "success": True,
                    "date": review_date.isoformat(),
                    "day_name": day_name,
                    "completed_today": completed,
                    "completed_count": len(completed),
                    "pending_today": pending,
                    "pending_count": len(pending),
                    "in_progress_today": in_progress,
                    "in_progress_count": len(in_progress),
                    "overdue_tasks": overdue,
                    "overdue_count": len(overdue),
                    "total_tasks": total,
                    "message": (
                        f"Review untuk {day_name}, {review_date.strftime('%d %B %Y')}"
                        if total > 0
                        else f"Tidak ada aktivitas tugas untuk {day_name}, {review_date.strftime('%d %B %Y')}."
                    ),
                }

        except Exception as e:
            logger.error(f"Failed to get evening review data for user {telegram_user_id}: {e}")
            return {"success": False, "error": "Gagal mengambil data review malam."}

    async def generate_review(
        self,
        telegram_user_id: int,
        target_date: Optional[str] = None,
    ) -> str:
        """Generate an evening review for a specific user."""
        data = await self.get_review_data(telegram_user_id, target_date)

        if not data.get("success"):
            return "🌙 *Selamat Malam!*\n\nTidak dapat mengambil progres tugas saat ini."

        provider = self._get_provider()
        if provider:
            try:
                prompt_data = (
                    f"Tanggal: {data.get('date')} ({data.get('day_name')})\n"
                    f"Total Tugas Terlibat: {data.get('total_tasks')}\n"
                    f"Tugas Selesai Hari Ini ({data.get('completed_count')}): "
                    f"{json.dumps(data.get('completed_today', []), ensure_ascii=False)}\n"
                    f"Tugas Pending/Tertunda ({data.get('pending_count')}): "
                    f"{json.dumps(data.get('pending_today', []), ensure_ascii=False)}\n"
                    f"Tugas Sedang Dikerjakan ({data.get('in_progress_count')}): "
                    f"{json.dumps(data.get('in_progress_today', []), ensure_ascii=False)}\n"
                    f"Tugas Overdue/Terlewat ({data.get('overdue_count')}): "
                    f"{json.dumps(data.get('overdue_tasks', []), ensure_ascii=False)}\n"
                    f"Pesan Default: {data.get('message')}"
                )
                review_text = await provider.generate_text(
                    prompt=prompt_data,
                    system_instruction=EVENING_REVIEW_PROMPT,
                )
                if review_text and review_text.strip():
                    return review_text.strip()
            except (LLMError, Exception) as e:
                logger.warning(
                    f"AI review generation failed for user {telegram_user_id}, "
                    f"using formatted fallback: {e}"
                )

        return self.format_fallback_review(data)

    @staticmethod
    def format_fallback_review(data: dict) -> str:
        """Generate a structured Markdown review directly from data as fallback."""
        day_name = data.get("day_name", "")
        date_str = data.get("date", "")
        total = data.get("total_tasks", 0)

        lines = [f"🌙 *Selamat Malam! Review {day_name} ({date_str})*\n"]

        if total == 0:
            lines.append("Tidak ada aktivitas tugas yang tercatat hari ini.")
            lines.append("\nWaktunya bersantai dan istirahat! 😴")
            return "\n".join(lines)

        completed = data.get("completed_today", [])
        if completed:
            lines.append("✅ *Tugas Selesai Hari Ini:*")
            for t in completed:
                lines.append(f"  • *{t.get('title')}*")
            lines.append("")

        pending = data.get("pending_today", [])
        if pending:
            lines.append("⏳ *Tertunda/Belum Selesai:*")
            for t in pending:
                lines.append(f"  • {t.get('title')}")
            lines.append("")

        in_progress = data.get("in_progress_today", [])
        if in_progress:
            lines.append("🚧 *Sedang Dikerjakan:*")
            for t in in_progress:
                lines.append(f"  • {t.get('title')}")
            lines.append("")

        overdue = data.get("overdue_tasks", [])
        if overdue:
            lines.append("⚠️ *Overdue / Terlewat:*")
            for t in overdue:
                lines.append(f"  ‼️ *{t.get('title')}*")
            lines.append("")

        lines.append("Terima kasih atas usahamu hari ini. Selamat beristirahat! 😴")
        return "\n".join(lines)

    async def send_evening_reviews(
        self,
        bot_application=None,
        target_date: Optional[str] = None,
        target_user_ids: Optional[list[int]] = None,
    ) -> list[dict]:
        """Generate and deliver evening reviews to users."""
        user_ids = target_user_ids
        if user_ids is None:
            user_ids = await self.get_registered_user_ids()

        results = []
        for user_id in user_ids:
            review_text = await self.generate_review(
                telegram_user_id=user_id,
                target_date=target_date,
            )

            sent = False
            if bot_application is not None and hasattr(bot_application, "bot"):
                try:
                    await bot_application.bot.send_message(
                        chat_id=user_id,
                        text=review_text,
                        parse_mode="Markdown",
                    )
                    sent = True
                    logger.info(f"Evening review sent to user {user_id}")
                except Exception as e:
                    logger.error(f"Failed to send evening review to user {user_id}: {e}")
            else:
                logger.warning(
                    f"No bot application provided — review generated for user {user_id} "
                    f"but not sent via Telegram"
                )

            results.append({
                "telegram_user_id": user_id,
                "sent": sent,
                "review": review_text,
            })

        return results
