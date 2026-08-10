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
├── app/
│   ├── ai/              # LLM provider abstraction
│   │   ├── __init__.py
│   │   └── base.py      # Abstract LLM interface
│   ├── api/             # FastAPI routes
│   │   ├── __init__.py
│   │   └── health.py    # Health check endpoint
│   ├── core/            # Configuration & logging
│   │   ├── __init__.py
│   │   ├── config.py    # Pydantic settings
│   │   └── logging.py   # Structured logging
│   ├── database/        # SQLAlchemy models & connection
│   ├── scheduler/       # APScheduler jobs
│   ├── services/        # Business logic & tools
│   ├── telegram/        # Telegram bot handlers
│   ├── __init__.py
│   └── main.py          # FastAPI app factory
├── tests/
│   ├── conftest.py      # Shared test fixtures
│   └── test_phase0.py   # Foundation tests
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

## Development Phases

- [x] **Phase 0** — Project Foundation
- [ ] **Phase 1** — Telegram Bot Integration
- [ ] **Phase 2** — Database (PostgreSQL + SQLAlchemy)
- [ ] **Phase 3** — Gemini AI Integration
- [ ] **Phase 4** — AI Tools (CRUD operations)
- [ ] **Phase 5** — Reminder Engine
- [ ] **Phase 6** — Daily Planner
- [ ] **Phase 7** — Morning Brief
- [ ] **Phase 8** — Evening Review
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
