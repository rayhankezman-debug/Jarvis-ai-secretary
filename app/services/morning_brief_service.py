"""
Morning brief service — generates and delivers proactive morning agendas.

This service is the business logic layer for Phase 7 (Morning Brief).
It:
1. Queries distinct Telegram user IDs from the database.
2. Reuses DailyPlanService to fetch structured task context for each user.
3. Formats task context using Gemini (LLMProvider) and MORNING_BRIEF_PROMPT.
4. Falls back gracefully to formatted task lists if AI generation fails or is unavailable.
5. Sends brief messages via Telegram bot application.

Security: All user briefs are strictly isolated by telegram_user_id.
"""

import json
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.ai.base import LLMProvider, LLMError
from app.ai.gemini import GeminiProvider
from app.ai.prompts import MORNING_BRIEF_PROMPT
from app.core.config import settings
from app.core.logging import get_logger
from app.database.models import Task
from app.database.session import get_db_session
from app.services.daily_plan_service import DailyPlanService

logger = get_logger(__name__)
TZ = ZoneInfo(settings.timezone)


class MorningBriefService:
    """
    Service for generating and dispatching daily morning briefs.

    All static and instance methods respect user isolation.
    """

    def __init__(self, llm_provider: Optional[LLMProvider] = None):
        """
        Initialize MorningBriefService.

        Args:
            llm_provider: Optional LLMProvider instance (for dependency injection/testing).
        """
        self._llm_provider = llm_provider

    def _get_provider(self) -> Optional[LLMProvider]:
        """Get or initialize LLM provider safely."""
        if self._llm_provider is not None:
            return self._llm_provider
        try:
            if settings.gemini_api_key:
                return GeminiProvider()
        except Exception as e:
            logger.warning(f"Failed to auto-initialize GeminiProvider for MorningBriefService: {e}")
        return None

    @staticmethod
    async def get_registered_user_ids() -> list[int]:
        """
        Query all distinct Telegram user IDs that have tasks in the database.

        Returns:
            List of Telegram user IDs.
        """
        try:
            async with get_db_session() as session:
                query = select(Task.telegram_user_id).distinct()
                result = await session.execute(query)
                user_ids = [row[0] for row in result.all() if row[0] is not None]
                return user_ids
        except Exception as e:
            logger.error(f"Failed to query registered user IDs for morning brief: {e}")
            return []

    async def generate_brief(
        self,
        telegram_user_id: int,
        target_date: Optional[str] = None,
    ) -> str:
        """
        Generate a morning brief for a specific user.

        Args:
            telegram_user_id: Telegram user ID.
            target_date: Optional target date in ISO 8601 format (YYYY-MM-DD).

        Returns:
            Markdown-formatted brief message.
        """
        # Fetch structured daily plan using Phase 6 DailyPlanService
        plan = await DailyPlanService.get_daily_plan(
            telegram_user_id=telegram_user_id,
            target_date=target_date,
        )

        if not plan.get("success"):
            return "🌅 *Selamat Pagi!*\n\nTidak dapat mengambil agenda tugas saat ini."

        # Try generating via LLM Provider
        provider = self._get_provider()
        if provider:
            try:
                prompt_data = (
                    f"Tanggal: {plan.get('date')} ({plan.get('day_name')})\n"
                    f"Total Tugas: {plan.get('total_tasks')}\n"
                    f"Tugas Terjadwal Hari Ini ({plan.get('scheduled_count')}): "
                    f"{json.dumps(plan.get('scheduled_tasks', []), ensure_ascii=False)}\n"
                    f"Tugas Overdue/Terlewat ({plan.get('overdue_count')}): "
                    f"{json.dumps(plan.get('overdue_tasks', []), ensure_ascii=False)}\n"
                    f"Tugas Backlog ({plan.get('backlog_count')}): "
                    f"{json.dumps(plan.get('backlog_tasks', []), ensure_ascii=False)}\n"
                    f"Pesan Default: {plan.get('message')}"
                )
                brief_text = await provider.generate_text(
                    prompt=prompt_data,
                    system_instruction=MORNING_BRIEF_PROMPT,
                )
                if brief_text and brief_text.strip():
                    return brief_text.strip()
            except (LLMError, Exception) as e:
                logger.warning(
                    f"AI brief generation failed for user {telegram_user_id}, "
                    f"using formatted fallback: {e}"
                )

        # Fallback formatting if AI generation fails or provider unavailable
        return self.format_fallback_brief(plan)

    @staticmethod
    def format_fallback_brief(plan: dict) -> str:
        """
        Generate a structured Markdown brief directly from plan data as a fallback.

        Args:
            plan: Result dict from DailyPlanService.get_daily_plan.

        Returns:
            Markdown-formatted fallback morning brief.
        """
        day_name = plan.get("day_name", "")
        date_str = plan.get("date", "")
        total = plan.get("total_tasks", 0)

        lines = [f"🌅 *Selamat Pagi! Ringkasan Pagi {day_name} ({date_str})*\n"]

        if total == 0:
            lines.append("🎉 Tidak ada tugas yang terjadwal untuk hari ini. Nikmati hari bebasmu!")
            lines.append("\nTetap jaga semangat dan kesehatan! 💪")
            return "\n".join(lines)

        overdue = plan.get("overdue_tasks", [])
        if overdue:
            lines.append("⚠️ *Tugas Overdue yang Perlu Perhatian:*")
            for t in overdue:
                priority_flag = "‼️ " if t.get("priority") in ("urgent", "high") else "• "
                lines.append(f"  {priority_flag}*{t.get('title')}* (Due: {t.get('due_date', 'Tanpa waktu')})")
            lines.append("")

        scheduled = plan.get("scheduled_tasks", [])
        if scheduled:
            lines.append("📅 *Jadwal Hari Ini:*")
            for t in scheduled:
                priority_flag = "⭐ " if t.get("priority") in ("urgent", "high") else "• "
                lines.append(f"  {priority_flag}*{t.get('title')}*")
            lines.append("")

        backlog = plan.get("backlog_tasks", [])
        if backlog:
            lines.append("💡 *Backlog & Prioritas Tambahan:*")
            for t in backlog[:3]:  # Top 3 backlog items
                lines.append(f"  • {t.get('title')}")
            lines.append("")

        lines.append("Semoga harimu produktif dan menyenangkan! 💪")
        return "\n".join(lines)

    async def send_morning_briefs(
        self,
        bot_application=None,
        target_date: Optional[str] = None,
        target_user_ids: Optional[list[int]] = None,
    ) -> list[dict]:
        """
        Generate and deliver morning briefs to users.

        Args:
            bot_application: Optional python-telegram-bot Application instance.
            target_date: Optional target date string.
            target_user_ids: Optional list of user IDs to send to (defaults to all in DB).

        Returns:
            List of status dicts per user: [{"telegram_user_id": int, "sent": bool, "brief": str}]
        """
        user_ids = target_user_ids
        if user_ids is None:
            user_ids = await self.get_registered_user_ids()

        results = []
        for user_id in user_ids:
            brief_text = await self.generate_brief(
                telegram_user_id=user_id,
                target_date=target_date,
            )

            sent = False
            if bot_application is not None and hasattr(bot_application, "bot"):
                try:
                    await bot_application.bot.send_message(
                        chat_id=user_id,
                        text=brief_text,
                        parse_mode="Markdown",
                    )
                    sent = True
                    logger.info(f"Morning brief sent to user {user_id}")
                except Exception as e:
                    logger.error(f"Failed to send morning brief to user {user_id}: {e}")
            else:
                logger.warning(
                    f"No bot application provided — brief generated for user {user_id} "
                    f"but not sent via Telegram"
                )

            results.append({
                "telegram_user_id": user_id,
                "sent": sent,
                "brief": brief_text,
            })

        return results
