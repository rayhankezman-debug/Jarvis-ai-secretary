# AI Secretary 🤖📋

Personal AI assistant for managing tasks, events, deadlines, schedules, and reminders through Telegram.

## Overview

AI Secretary understands natural language (including Bahasa Indonesia) and helps you manage your daily life:

- **Task Management** — Create, update, delete, and complete tasks via natural language
- **Daily Planner** — AI-generated schedule proposals based on your activities
- **Reminders** — Automatic notifications before events and deadlines
- **Morning Brief** — Daily agenda summary every morning
- **Evening Review** — End-of-day progress report

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | Python + FastAPI |
| AI | Google Gemini API (Free Tier) |
| Interface | Telegram Bot |
| Database | PostgreSQL + SQLAlchemy |
| Scheduler | APScheduler |
| Validation | Pydantic |

## Project Structure

```
JARVIS/
├── alembic/             # Database migrations (Alembic)
│   ├── versions/        # Migration scripts
│   └── env.py           # Async migration environment
├── app/
│   ├── ai/              # LLM provider abstraction + AI agent
│   │   ├── __init__.py
│   │   ├── base.py      # Abstract LLM interface
│   │   ├── gemini.py    # Google Gemini implementation
│   │   ├── prompts.py   # System prompts
│   │   ├── agent.py     # AI agent with tool-calling (Phase 4)
│   │   └── tools.py     # Gemini function declarations (Phase 4)
│   ├── api/             # FastAPI routes
│   │   ├── __init__.py
│   │   └── health.py    # Health check endpoint (+ DB status)
│   ├── core/            # Configuration & logging
│   │   ├── __init__.py
│   │   ├── config.py    # Pydantic settings
│   │   └── logging.py   # Structured logging
│   ├── database/        # SQLAlchemy models & connection
│   │   ├── __init__.py  # Public API exports
│   │   ├── base.py      # Declarative base + TimestampMixin
│   │   ├── models.py    # Task model + enums
│   │   └── session.py   # Async engine & session factory
│   ├── scheduler/       # APScheduler reminder engine (Phase 5)
│   │   ├── __init__.py  # Package exports
│   │   ├── engine.py    # Scheduler lifecycle + job management
│   │   └── reminder_service.py  # Reminder logic + deduplication
│   ├── services/        # Business logic & tools
│   │   ├── __init__.py
│   │   ├── task_service.py  # Task CRUD scoped by user (Phase 4)
│   │   ├── daily_plan_service.py  # Daily planner data layer (Phase 6)
│   │   └── morning_brief_service.py  # Proactive morning brief (Phase 7)
│   ├── telegram/        # Telegram bot handlers
│   │   ├── __init__.py
│   │   ├── bot.py       # Bot application factory
│   │   └── handlers.py  # Command & message handlers (agent routing)
│   ├── __init__.py
│   └── main.py          # FastAPI app factory + bot lifecycle
├── tests/
│   ├── conftest.py      # Shared test fixtures
│   ├── test_phase0.py   # Foundation tests (9 tests)
│   ├── test_phase1.py   # Telegram bot tests (15 tests)
│   ├── test_phase2.py   # Database tests (29 tests)
│   ├── test_phase3.py   # Gemini AI tests (26 tests)
│   ├── test_phase4.py   # AI agent + tools tests (61 tests)
│   ├── test_phase5.py   # Reminder engine tests (46 tests)
│   ├── test_phase6.py   # Daily planner tests (39 tests)
│   └── test_phase7.py   # Morning brief tests (19 tests)
├── alembic.ini          # Alembic configuration
├── .env.example         # Environment variable template
├── .gitignore
├── pytest.ini           # Test configuration
├── requirements.txt     # Python dependencies
├── run.py               # Application entry point
└── README.md
```

## Quick Start

### 1. Clone & Setup

```bash
git clone <repository-url>
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

### 3. Run the Application

```bash
python run.py
```

The API will be available at `http://localhost:8000`.

### 4. Run Tests

```bash
pytest -v
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Application health check |
| GET | `/docs` | Swagger UI (auto-generated) |

## Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message & bot introduction |
| `/help` | List available commands |
| `/ping` | Connectivity check (returns server time) |

## Development Phases

- [x] **Phase 0** — Project Foundation
- [x] **Phase 1** — Telegram Bot Integration
- [x] **Phase 2** — Database (PostgreSQL + SQLAlchemy)
- [x] **Phase 3** — Gemini AI Integration
- [x] **Phase 4** — AI Agent Tools (task CRUD via function calling)
- [x] **Phase 5** — Reminder Engine
- [x] **Phase 6** — Daily Planner
- [x] **Phase 7** — Morning Brief
- [x] **Phase 8** — Evening Review
- [ ] **Phase 9** — History & Statistics
- [ ] **Phase 10** — Testing & Hardening
- [ ] **Phase 11** — Deployment

## Environment Variables

See `.env.example` for all required variables.

| Variable | Description |
|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API token |
| `GEMINI_API_KEY` | Google Gemini API key |
| `GEMINI_MODEL` | Gemini model name |
| `DATABASE_URL` | PostgreSQL connection string |
| `TIMEZONE` | Default timezone (Asia/Jakarta) |

## License

Private project.
