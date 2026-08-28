"""
SQLAlchemy database models.

Phase 2 defines the core Task model that the AI Secretary manages.
Future phases will add more models (e.g., Event, Reminder, DailyPlan).

Each model maps to a PostgreSQL table. SQLAlchemy handles the
SQL generation, type mapping, and relationship management.

Model design principles:
- Use enums for fixed-choice fields (status, priority)
- Store times in UTC, display in user's timezone
- Keep models focused — one model per concept
- Use nullable=False for required fields
"""

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin


class TaskStatus(str, enum.Enum):
    """
    Lifecycle states for a task.

    Flow: pending → in_progress → completed
                                → cancelled

    Using str enum so it serializes nicely to JSON.
    """
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TaskPriority(str, enum.Enum):
    """
    Priority levels for tasks.

    The AI will suggest priorities based on context,
    but users can override them.
    """
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class Task(Base, TimestampMixin):
    """
    Core task model — the primary entity managed by the AI Secretary.

    A task represents something the user needs to do. It can be:
    - A simple to-do: "Beli susu"
    - A scheduled event: "Meeting jam 2 siang"
    - A deadline: "Submit tugas before Friday"

    Fields:
        id: Auto-incrementing primary key
        telegram_user_id: Links task to a Telegram user (BigInteger for Telegram IDs)
        title: Short task description (extracted by AI from natural language)
        description: Optional longer description or notes
        status: Current lifecycle state (pending, in_progress, completed, cancelled)
        priority: Importance level (low, medium, high, urgent)
        due_date: Optional deadline or scheduled time (stored in UTC)
        completed_at: When the task was marked complete
        created_at: When the task was created (from TimestampMixin)
        updated_at: Last modification time (from TimestampMixin)
    """

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    telegram_user_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        index=True,
        comment="Telegram user ID who owns this task",
    )
    title: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="Short task description",
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
        comment="Optional detailed description or notes",
    )
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status", native_enum=False),
        nullable=False,
        default=TaskStatus.PENDING,
        server_default=TaskStatus.PENDING.value,
        index=True,
        comment="Current task lifecycle state",
    )
    priority: Mapped[TaskPriority] = mapped_column(
        Enum(TaskPriority, name="task_priority", native_enum=False),
        nullable=False,
        default=TaskPriority.MEDIUM,
        server_default=TaskPriority.MEDIUM.value,
        comment="Task importance level",
    )
    due_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="Optional deadline or scheduled time (UTC)",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="When the task was completed",
    )

    def __repr__(self) -> str:
        return (
            f"<Task(id={self.id}, title='{self.title[:30]}...', "
            f"status={self.status.value}, priority={self.priority.value})>"
        )

    def mark_completed(self) -> None:
        """Mark this task as completed with the current timestamp."""
        self.status = TaskStatus.COMPLETED
        self.completed_at = datetime.now(tz=__import__("zoneinfo").ZoneInfo("UTC"))

    def mark_cancelled(self) -> None:
        """Mark this task as cancelled."""
        self.status = TaskStatus.CANCELLED


class MessageRole(str, enum.Enum):
    """
    Role of the sender in a conversation message.
    """
    USER = "user"
    MODEL = "model"


class ConversationMessage(Base, TimestampMixin):
    """
    Stores short-term conversation history for context.
    """
    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    telegram_user_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        index=True,
        comment="Telegram user ID who owns this message",
    )
    role: Mapped[MessageRole] = mapped_column(
        Enum(MessageRole, name="message_role", native_enum=False),
        nullable=False,
        comment="Role of the sender (user or model)",
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="The text content of the message",
    )

    def __repr__(self) -> str:
        return f"<ConversationMessage(id={self.id}, role={self.role.value}, content='{self.content[:30]}...')>"


class LongTermMemory(Base, TimestampMixin):
    """
    Stores long-term memory/facts about the user.
    """
    __tablename__ = "long_term_memories"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    telegram_user_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        index=True,
        comment="Telegram user ID who owns this memory",
    )
    category: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="Category of the memory (e.g. identity, preference, habit, other)",
    )
    fact: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="The actual fact/memory stored",
    )

    def __repr__(self) -> str:
        return f"<LongTermMemory(id={self.id}, category='{self.category}', fact='{self.fact[:30]}...')>"
