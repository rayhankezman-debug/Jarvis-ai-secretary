# JARVIS — AI Secretary 🤖📋

> Personal AI secretary that manages tasks, schedules, reminders, and daily planning through natural language conversations on Telegram — powered by Google Gemini's function-calling capabilities.

![Python](https://img.shields.io/badge/Python-3.13-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-4169E1?logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)
![Tests](https://img.shields.io/badge/Tests-391%20passed-brightgreen?logo=pytest&logoColor=white)
![License](https://img.shields.io/badge/License-Private-lightgrey)

---

## Overview

> **Project Status**: This repository is currently focused on serving as a comprehensive GitHub portfolio project. It is fully containerized and production-ready, but is not currently deployed to a live VPS.

JARVIS is a Telegram-based AI personal secretary built with a **Gemini-powered autonomous agent** that understands natural language commands in **Bahasa Indonesia and English**. Instead of rigid command menus, users simply chat with the bot — the AI agent decides which tools to invoke, executes multi-step operations, and responds in natural language.

The system features a **multi-tier reminder engine**, **AI-generated morning briefs and evening reviews**, **dual memory architecture** (short-term conversation history + long-term persistent memory), and **productivity statistics** — all orchestrated through Gemini's function-calling API with strict multi-user data isolation.

---

## Key Features

| Feature | Description |
|---------|-------------|
| 🗂️ **Task Management** | Create, list, update, complete, cancel, and batch-cancel tasks via natural language |
| 📅 **AI Daily Planner** | AI-generated daily schedules based on scheduled, overdue, and backlog tasks |
| ⏰ **Multi-Tier Reminders** | Automatic notifications at H-7, H-3, H-1, H-0, 30 min before, and overdue |
| 🌅 **Morning Brief** | Proactive daily agenda delivered every morning via Telegram |
| 🌙 **Evening Review** | End-of-day progress summary with task completion analysis |
| 💬 **Conversational Memory** | Short-term chat history (last 10 messages) for context-aware multi-turn dialogue |
| 🧠 **Long-Term Memory** | Persistent storage of user preferences, habits, and identity facts |
| 📊 **Productivity Statistics** | Completion rates, task counts by status, most productive day analysis |
| 🌐 **Bilingual Support** | Responds in the user's language (Bahasa Indonesia or English) |
| 🔒 **Multi-User Isolation** | All data is strictly scoped by `telegram_user_id` |

---

## Demo

<!-- TODO: Add screenshot of natural-language task creation conversation in Telegram -->

<!-- TODO: Add screenshot of daily planner / agenda response -->

<!-- TODO: Add screenshot of morning brief or evening review message -->

<!-- TODO: Add screenshot of long-term memory interaction (saving and recalling preferences) -->

<!-- TODO: Add screenshot of reminder notification -->

<!-- TODO: Add screenshot of productivity statistics response -->

---

## Architecture Overview

```mermaid
flowchart TB
    User([User]) -->|Chat| TG[Telegram Bot]
    TG -->|Message| Handler[Telegram Handler]
    Handler -->|Save message| CHService[ChatHistoryService]
    Handler -->|Process| Agent[AgentService]
    Agent -->|System prompt + tools + history| Gemini[Google Gemini API]
    Gemini -->|function_call| Agent
    Agent -->|Execute tool| Tools[Tool Executor]
    Tools -->|CRUD| TaskService[TaskService]
    Tools -->|Plan| DailyPlanService[DailyPlanService]
    Tools -->|Stats| HistoryService[HistoryService]
    Tools -->|Memory| MemoryService[MemoryService]
    TaskService --> DB[(PostgreSQL)]
    DailyPlanService --> DB
    HistoryService --> DB
    MemoryService --> DB
    CHService --> DB
    Agent -->|Text response| Handler
    Handler -->|Reply| TG
    TG -->|Message| User

    Scheduler[APScheduler] -->|Every 5 min| ReminderService[ReminderService]
    Scheduler -->|Cron daily| MorningBrief[MorningBriefService]
    Scheduler -->|Cron daily| EveningReview[EveningReviewService]
    ReminderService --> DB
    MorningBrief --> DB
    EveningReview --> DB
    ReminderService -->|Notification| TG
    MorningBrief -->|Brief| TG
    EveningReview -->|Review| TG

    style Gemini fill:#4285F4,color:#fff
    style DB fill:#4169E1,color:#fff
    style Scheduler fill:#FF9800,color:#fff
```

---

## How It Works

1. **User sends a message** to the Telegram bot in natural language (e.g., *"Besok jam 8 kuliah, jam 2 meeting"*)
2. **Telegram handler** saves the message to conversation history, then forwards it to the `AgentService`
3. **AgentService** builds a context with the system prompt, last 10 conversation messages, and tool definitions, then sends it to **Gemini**
4. **Gemini analyzes** the message and returns either a text response or a `function_call` (e.g., `create_task`)
5. **Tool executor** runs the requested function against the appropriate service (e.g., `TaskService.create_task`), injecting the trusted `telegram_user_id`
6. **Tool result** is sent back to Gemini, which may call another tool or generate a final text response
7. **Multi-turn loop** continues for up to `MAX_TOOL_TURNS = 5` iterations (e.g., Gemini calls `list_tasks` to find a task ID, then calls `complete_task` with that ID)
8. **Final response** is sent back to the user via Telegram and saved to conversation history

---

## AI Agent & Tool Calling

The core of JARVIS is the `AgentService` — an autonomous AI agent that uses **Gemini's function-calling API** with manual tool execution (automatic function calling is explicitly disabled).

### Tool-Calling Architecture

- **SDK**: `google-genai` with async client (`client.aio.models.generate_content`)
- **Manual dispatch**: Automatic function calling is disabled via `AutomaticFunctionCallingConfig(disable=True)` — the agent controls the execution loop
- **Multi-turn support**: Up to **5 sequential tool calls** per user message (`MAX_TOOL_TURNS = 5`)
- **Thought signature preservation**: The agent appends Gemini's raw `candidate.content` (not a reconstructed object) to preserve `thought_signature` fields required by newer Gemini models
- **Trusted user ID injection**: `telegram_user_id` is injected by the handler, never from AI output or user input

### Registered Tools

There are currently **12 AI tools** (8 task tools + 4 memory tools) defined as Gemini `FunctionDeclaration` objects in `app/ai/tools.py`:

| Tool | Service | Description |
|------|---------|-------------|
| `create_task` | TaskService | Create a new task with title, description, due date, and priority |
| `list_tasks` | TaskService | List/search tasks with filters (status, date range, title search) |
| `update_task` | TaskService | Update task details (title, description, due date, priority) |
| `complete_task` | TaskService | Mark a task as completed |
| `cancel_task` | TaskService | Cancel a single task |
| `batch_cancel_tasks` | TaskService | Cancel multiple tasks at once; handles ambiguous "bersihkan" requests by asking for clarification |
| `generate_daily_plan` | DailyPlanService | Generate a structured daily plan for a target date (excludes cancelled tasks) |
| `get_productivity_statistics` | HistoryService | Calculate productivity metrics for a date range |
| `save_memory` | MemoryService | Store a long-term fact about the user |
| `search_memory` | MemoryService | Search stored memories by keyword and/or category |
| `update_memory` | MemoryService | Update an existing memory fact |
| `delete_memory` | MemoryService | Delete a memory fact |

---

## Memory System

JARVIS implements a **dual memory architecture**:

### Short-Term Memory (Conversation History)

- Stored in the `conversation_messages` table
- Managed by `ChatHistoryService`
- Last **10 messages** are injected into the Gemini context on each request
- Provides multi-turn conversation context (e.g., follow-up questions, pronoun resolution)
- Each message stores `role` (`user` or `model`) and `content`

### Long-Term Memory (Persistent Facts)

- Stored in the `long_term_memories` table
- Managed by `MemoryService`, exposed as Gemini tools (`save_memory`, `search_memory`, `update_memory`, `delete_memory`)
- The AI agent autonomously decides when to save, recall, or update memories
- Organized by category:

| Category | Examples |
|----------|----------|
| `identity` | User's name, occupation, university |
| `preference` | Favorite drink, preferred schedule style |
| `habit` | Morning routine, study patterns |
| `other` | Miscellaneous long-term facts |

- Search uses PostgreSQL `ILIKE` for case-insensitive substring matching
- All memory operations enforce `telegram_user_id` isolation

---

## Reminder System

The reminder engine (`ReminderService` + `SchedulerEngine`) uses APScheduler to periodically check for upcoming task deadlines and send Telegram notifications.

### Reminder Tiers

| Tier | Trigger | Message |
|------|---------|---------|
| **H-7** | 7 days before due date | "📢 Reminder 7 hari lagi!" |
| **H-3** | 3 days before due date | "📢 Reminder 3 hari lagi!" |
| **H-1** | 1 day before (24–48h) | "📢 Reminder besok!" |
| **H-0** | Same day (0.5–24h) | "📅 Reminder hari ini!" |
| **DUE_SOON** | Within 30 minutes | "🔔 Tugas segera!" |
| **OVERDUE** | Past due date | "⚠️ Tugas sudah lewat deadline!" |

### Key Behaviors

- **Deduplication**: In-memory `set` of `(task_id, reminder_type)` prevents duplicate notifications within a session
- **Retroactive suppression**: H-7 and H-3 reminders are skipped if the task was created after the reminder window (e.g., a task created 2 days before its due date won't receive an H-7 reminder)
- **Check interval**: Every 5 minutes (configurable via `DEFAULT_CHECK_INTERVAL_MINUTES`)
- **Active tasks only**: Only tasks with status `PENDING` or `IN_PROGRESS` receive reminders
- **Timezone-aware**: All time calculations use the configured timezone (default: `Asia/Jakarta`)

---

## Daily Planner

The `generate_daily_plan` tool (backed by `DailyPlanService`) aggregates a user's tasks for a target date into three categories:

1. **Scheduled tasks**: Active tasks with `due_date` on the target date, sorted by time
2. **Overdue tasks**: Active tasks with `due_date` before the target date
3. **Backlog tasks**: Active tasks without a `due_date`, sorted by creation date

The structured data is returned to Gemini, which formats it into a natural-language daily schedule with productivity suggestions.

---

## Morning Brief & Evening Review

### Morning Brief

- **Trigger**: Daily cron job at configurable time (default: `07:00`)
- **Process**: Queries all registered users → fetches daily plan data → generates AI-formatted brief via Gemini using `MORNING_BRIEF_PROMPT` → sends via Telegram
- **Fallback**: If Gemini is unavailable, a structured Markdown template is used
- **Content**: Overdue alerts, today's scheduled tasks, backlog priorities, motivational message

### Evening Review

- **Trigger**: Daily cron job at configurable time (default: `20:00`)
- **Process**: Queries completed/pending/in-progress/overdue tasks for the day → generates AI-formatted review via Gemini using `EVENING_REVIEW_PROMPT` → sends via Telegram
- **Fallback**: Structured Markdown fallback if AI generation fails
- **Content**: Completed tasks celebration, pending tasks reminder, overdue warnings, rest wishes

Both services auto-discover users by querying distinct `telegram_user_id` values from the `tasks` table.

---

## Productivity Statistics

The `get_productivity_statistics` tool (backed by `HistoryService`) calculates:

- Total tasks in the date range
- Counts by status: completed, pending, in-progress, cancelled
- Overdue task count
- **Completion rate** (completed ÷ active tasks, excluding cancelled)
- **Most productive day** (day with the most completions)
- **Completed-by-day breakdown** (daily completion counts)

---

## Database Architecture

```mermaid
erDiagram
    tasks {
        int id PK
        bigint telegram_user_id
        varchar title
        text description
        enum status
        enum priority
        datetime due_date
        datetime completed_at
        datetime created_at
        datetime updated_at
    }

    conversation_messages {
        int id PK
        bigint telegram_user_id
        enum role
        text content
        datetime created_at
        datetime updated_at
    }

    long_term_memories {
        int id PK
        bigint telegram_user_id
        varchar category
        text fact
        datetime created_at
        datetime updated_at
    }
```

- **`tasks`**: Core entity — stores tasks with status (`pending`, `in_progress`, `completed`, `cancelled`), priority (`low`, `medium`, `high`, `urgent`), and optional due date
- **`conversation_messages`**: Short-term chat history with role (`user`, `model`) for multi-turn context
- **`long_term_memories`**: Persistent user facts with category-based organization
- All tables include `telegram_user_id` for multi-user isolation and `TimestampMixin` (`created_at`, `updated_at`)
- Migrations managed via **Alembic** with 3 migration scripts (initial tables → conversation messages → long-term memories)

---

## Tech Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| **Runtime** | Python | 3.13 |
| **Web Framework** | FastAPI | 0.115.12 |
| **ASGI Server** | Uvicorn | 0.34.2 |
| **AI Engine** | Google Gemini (`google-genai`) | ≥1.50.0 |
| **Chat Interface** | python-telegram-bot | 22.8 |
| **Database** | PostgreSQL | 15 |
| **ORM** | SQLAlchemy (async) | 2.0.41 |
| **DB Driver** | asyncpg | 0.30.0 |
| **Migrations** | Alembic | 1.16.1 |
| **Scheduler** | APScheduler | 3.11.0 |
| **Validation** | Pydantic + Pydantic Settings | 2.11.3 / 2.9.1 |
| **Containerization** | Docker + Docker Compose | — |
| **Testing** | pytest + pytest-asyncio | 8.4.0 / 0.26.0 |
| **Test HTTP Client** | httpx | 0.28.1 |
| **Test DB** | aiosqlite | 0.21.0 |

---

## Testing

The project has a comprehensive test suite with **391 tests** across **18 test files**, along with validated manual Telegram testing for interactive agent behaviors:

```
tests/
├── conftest.py                  # Shared fixtures
├── test_phase0.py               # Project foundation
├── test_phase1.py               # Telegram bot integration
├── test_phase2.py               # Database models & CRUD
├── test_phase3.py               # Gemini AI provider
├── test_phase4.py               # AI agent & tool calling
├── test_phase5.py               # Reminder engine
├── test_phase6.py               # Daily planner
├── test_phase7.py               # Morning brief
├── test_phase8.py               # Evening review
├── test_phase9.py               # History & statistics
├── test_phase10.py              # Integration hardening
├── test_phase11.py              # Docker & deployment
├── test_phase12_chat_history.py # Conversational memory
├── test_phase12_fixes.py        # Agent stability & SDK compatibility
├── test_phase13b.py             # Long-term memory
├── test_batch_cancel.py         # Batch task cancellation & isolation
├── test_memory_service.py       # Memory service unit tests
└── test_task_retrieval_audit.py # Task retrieval flow audit
```

### Running Tests

```bash
pytest -v
```

> **Note**: Some `RuntimeWarning` messages related to async event loop teardown may appear during test runs. These are upstream runtime artifacts from `pytest-asyncio` and do not indicate test failures.

---

## Security Considerations

| Protection | Implementation |
|-----------|----------------|
| **Secret management** | All secrets loaded from `.env` file via Pydantic Settings; `.env` is in `.gitignore` |
| **User data isolation** | Every database query (including batch operations) is scoped by `telegram_user_id` |
| **Trusted ID injection** | `telegram_user_id` comes from the Telegram handler (trusted), never from AI output or user input |
| **Anti-hallucination** | System prompt strictly forbids the AI from claiming success (e.g., for cancellations) unless the tool returns success |
| **SQL injection prevention** | SQLAlchemy ORM with parameterized queries — no raw SQL |
| **Tool execution limits** | `MAX_TOOL_TURNS = 5` prevents infinite tool-calling loops |
| **Rate limit handling** | Gemini 429/resource-exhausted errors are caught and surfaced as user-friendly messages |
| **Log redaction** | `SensitiveDataFilter` automatically redacts API keys, bot tokens, and database URLs from log output |
| **Non-root container** | Docker runs as `appuser` (non-root) for defense in depth |
| **No eval/exec** | No dynamic code execution anywhere in the codebase |

---

## Local Development Setup

### Prerequisites

- Python 3.13+
- PostgreSQL 15+
- A [Telegram Bot Token](https://core.telegram.org/bots#botfather) from @BotFather
- A [Google Gemini API Key](https://aistudio.google.com/apikey)

### 1. Clone & Install

```bash
git clone https://github.com/rayhankezman-debug/Jarvis-ai-secretary.git
cd JARVIS
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
copy .env.example .env
# Edit .env with your actual credentials
```

### 3. Run Database Migrations

```bash
alembic upgrade head
```

### 4. Start the Application

```bash
python run.py
```

The API will be available at `http://localhost:8000`.

### 5. Run Tests

```bash
pytest -v
```

---

## Docker Setup

### Build and Start

```bash
docker compose up -d --build
```

### View Logs

```bash
docker compose logs -f app
```

### Stop

```bash
docker compose down
```

### Update After Code Changes

```bash
git pull
docker compose up -d --build
```

### Health Check

The application container includes a built-in health check:

```
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3
    CMD curl -f http://localhost:8000/health || exit 1
```

### Database Persistence

PostgreSQL data is stored in the `postgres_data` Docker volume and persists across container restarts. Database migrations are applied automatically on container startup via `scripts/start.sh`.

---

## Environment Variables

All configuration is managed via environment variables (loaded from `.env`):

| Variable | Description | Default |
|----------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API token from @BotFather | — |
| `GEMINI_API_KEY` | Google Gemini API key | — |
| `GEMINI_MODEL` | Gemini model name | `gemini-2.0-flash` |
| `DATABASE_URL` | PostgreSQL async connection string | `postgresql+asyncpg://user:password@localhost:5432/ai_secretary` |
| `TIMEZONE` | Default timezone for scheduling and display | `Asia/Jakarta` |
| `MORNING_BRIEF_TIME` | Time to send morning brief (HH:MM) | `07:00` |
| `ENABLE_MORNING_BRIEF` | Enable automated morning brief delivery | `true` |
| `EVENING_REVIEW_TIME` | Time to send evening review (HH:MM) | `20:00` |
| `ENABLE_EVENING_REVIEW` | Enable automated evening review delivery | `true` |
| `APP_ENV` | Environment: `development`, `staging`, `production` | `development` |
| `LOG_LEVEL` | Logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR` | `INFO` |

---

## Project Structure

```
JARVIS/
├── app/
│   ├── ai/                          # AI engine
│   │   ├── __init__.py              # LLM provider factory
│   │   ├── agent.py                 # AgentService — tool-calling orchestrator
│   │   ├── base.py                  # Abstract LLMProvider interface
│   │   ├── gemini.py                # Google Gemini implementation
│   │   ├── prompts.py              # System prompts (agent, morning brief, evening review)
│   │   └── tools.py                 # Gemini FunctionDeclarations + tool executor
│   ├── api/
│   │   ├── __init__.py
│   │   └── health.py                # Health check endpoint (+ DB status)
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py                # Pydantic Settings (single source of truth)
│   │   └── logging.py               # Structured logging + sensitive data filter
│   ├── database/
│   │   ├── __init__.py
│   │   ├── base.py                  # Declarative base + TimestampMixin
│   │   ├── models.py                # Task, ConversationMessage, LongTermMemory
│   │   └── session.py               # Async engine, session factory, connection pool
│   ├── scheduler/
│   │   ├── __init__.py
│   │   ├── engine.py                # APScheduler lifecycle + job registration
│   │   └── reminder_service.py      # Multi-tier reminder logic + deduplication
│   ├── services/
│   │   ├── __init__.py
│   │   ├── chat_history_service.py  # Short-term conversation memory
│   │   ├── daily_plan_service.py    # Daily planner data aggregation
│   │   ├── evening_review_service.py # Evening review generation + delivery
│   │   ├── history_service.py       # Productivity statistics
│   │   ├── memory_service.py        # Long-term memory CRUD
│   │   ├── morning_brief_service.py # Morning brief generation + delivery
│   │   └── task_service.py          # Task CRUD (scoped by user)
│   ├── telegram/
│   │   ├── __init__.py
│   │   ├── bot.py                   # Bot application factory + handler registration
│   │   └── handlers.py             # Command & message handlers (agent routing)
│   ├── __init__.py
│   └── main.py                      # FastAPI app factory + lifespan management
├── alembic/
│   ├── versions/
│   │   ├── 6c8fd5ab903d_initial_tables.py
│   │   ├── 230b8d52b7e7_add_conversationmessage.py
│   │   └── be14157ce529_add_long_term_memory.py
│   └── env.py                       # Async migration environment
├── scripts/
│   └── start.sh                     # Docker entrypoint (migrations + uvicorn)
├── tests/                           # 369 tests across 17 test files
│   ├── conftest.py
│   └── test_*.py
├── .dockerignore
├── .env.example
├── .gitignore
├── alembic.ini
├── docker-compose.yml
├── Dockerfile
├── pytest.ini
├── requirements.txt
├── run.py                           # Application entry point
└── README.md
```

---

## Development Phases

- [x] **Phase 0** — Project Foundation (FastAPI, config, logging, health check)
- [x] **Phase 1** — Telegram Bot Integration (commands, message handling)
- [x] **Phase 2** — Database (PostgreSQL, SQLAlchemy async, Task model)
- [x] **Phase 3** — Gemini AI Integration (LLM abstraction, text generation)
- [x] **Phase 4** — AI Agent & Tool Calling (function calling, task CRUD tools)
- [x] **Phase 5** — Reminder Engine (APScheduler, multi-tier reminders)
- [x] **Phase 6** — Daily Planner (AI-generated daily schedules)
- [x] **Phase 7** — Morning Brief (proactive daily agenda delivery)
- [x] **Phase 8** — Evening Review (end-of-day progress summary)
- [x] **Phase 9** — History & Statistics (productivity analytics)
- [x] **Phase 10** — Testing & Hardening (integration tests, edge cases)
- [x] **Phase 11** — Deployment (Docker, Docker Compose, health checks)
- [x] **Phase 12** — Conversational Memory (persistent chat history, SDK stabilization)
- [x] **Phase 13** — Long-Term Memory (persistent user facts & preferences)

---

## Roadmap

> These are potential future enhancements — **not existing features**.

- [ ] Webhook mode for Telegram (replace polling for lower latency)
- [ ] Calendar integration (Google Calendar sync)
- [ ] Voice message support
- [ ] Web dashboard for task visualization
- [ ] RAG-based memory retrieval for large memory stores
- [ ] Multi-provider LLM support (OpenAI, Anthropic)
- [ ] Task categories and tags
- [ ] Recurring tasks

---

## Author

**Rayhan Kezman Ramadhan**

- GitHub: [rayhankezman-debug](https://github.com/rayhankezman-debug)

---

## License

Private project.
