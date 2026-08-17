"""
Services package — business logic and tool implementations.

Public API:
    TaskService         — Task CRUD operations scoped by user
    DailyPlanService    — Daily plan generation from tasks (Phase 6)
    MorningBriefService — Proactive morning brief generator (Phase 7)
    EveningReviewService— Proactive evening summary generator (Phase 8)
"""

from app.services.task_service import TaskService
from app.services.daily_plan_service import DailyPlanService
from app.services.morning_brief_service import MorningBriefService
from app.services.evening_review_service import EveningReviewService

__all__ = [
    "TaskService",
    "DailyPlanService",
    "MorningBriefService",
    "EveningReviewService",
]
