# CLAUDE.md — PBEM_Client Codebase Guide

This file provides AI assistants with essential context about the **PBEM_Client** project: its purpose, architecture, conventions, and development workflows.

---

## Project Overview

**PBEM_Client** is a Play-By-Email (PBEM) coordination platform for asynchronous turn-based games (e.g., Civilization IV). It lets players upload/download savegame files to a central server, which rotates turns and optionally notifies players via email.

The project is branded internally as **STRAT//COM**.

**Three components live in this repo:**

| Component | Path | Purpose |
|-----------|------|---------|
| Flask Web App | `app/` | Primary UI with lobbies, chat, notes, savegame management |
| Legacy REST API | `server/` | JSON-only API server (standalone, older implementation) |
| CLI Client | `client/` | Command-line client for the REST API |

The primary active development surface is `app/`. The `server/` is a reference/legacy implementation.

---

## Tech Stack

- **Language:** Python 3
- **Web Framework:** Flask 3.0.3 (with Jinja2 templates)
- **ORM:** Flask-SQLAlchemy 3.1
- **Database:** SQLite (development) / PostgreSQL (production)
- **Password Hashing:** Werkzeug
- **Production Server:** Gunicorn (1 worker, 4 threads)
- **Frontend:** Jinja2 HTML templates, vanilla JS (AJAX polling), custom CSS
- **HTTP Client (CLI):** Requests 2.32.3
- **Deployment:** Railway.app (primary), Heroku-compatible

---

## Repository Structure

```
PBEM_Client/
├── run.py                  # Entry point → calls create_app()
├── requirements.txt        # Root dependencies (Flask, SQLAlchemy, Gunicorn, psycopg2)
├── Procfile                # Heroku/Railway: gunicorn run:app ...
├── railway.toml            # Railway.app deployment config
├── app/                    # Primary Flask application
│   ├── __init__.py         # App factory: create_app(), login_required, context processors
│   ├── config.py           # Config class (DATABASE_URL, SECRET_KEY, UPLOAD_FOLDER)
│   ├── models.py           # SQLAlchemy ORM models
│   ├── auth/
│   │   └── routes.py       # /auth/register, /auth/login, /auth/logout
│   ├── lobby/
│   │   └── routes.py       # / (list), /create, /<id> (detail), /<id>/join, etc.
│   ├── savegame/
│   │   └── routes.py       # /upload/<id>, /download/<id>
│   └── templates/
│       ├── base.html       # Shared layout (cyberpunk CSS, purple grid animation)
│       ├── auth/           # login.html, register.html
│       └── lobby/          # list.html, create.html, detail.html
├── server/                 # Legacy standalone REST API (JSON-only)
│   ├── app.py              # ~600-line single-file Flask app
│   ├── init_db.py          # DB initialization
│   └── requirements.txt
├── client/                 # CLI client for the REST API
│   ├── pbem_client.py      # ~366-line CLI with token persistence
│   └── requirements.txt
└── uploads/                # Savegame file storage (gitignored)
```

---

## Data Models (`app/models.py`)

| Model | Key Fields | Notes |
|-------|-----------|-------|
| `User` | `username`, `password_hash`, `created_at` | Auth entity |
| `Lobby` | `name`, `owner_id`, `max_players`, `status`, `current_turn_index`, `is_locked` | Central game session |
| `LobbyMember` | `lobby_id`, `user_id`, `play_order` | M2M with ordering |
| `SavegameFile` | `lobby_id`, `uploader_id`, `filename`, `filepath`, `round_number`, `uploaded_at` | File metadata |
| `PlayerNote` | `lobby_id`, `user_id`, `round_number`, `content` | Per-player notes; `round_number=None` = general note |
| `ChatMessage` | `lobby_id`, `user_id`, `content`, `timestamp` | In-game chat |

**Lobby statuses:** `waiting` → (lock) → `active` → (finish) → `finished`

---

## Route Reference (`app/`)

### Auth Blueprint (`/auth`)
| Method | Route | Description |
|--------|-------|-------------|
| GET/POST | `/auth/register` | Create account |
| GET/POST | `/auth/login` | Authenticate (sets session) |
| POST | `/auth/logout` | Clear session |

### Lobby Blueprint (`/`)
| Method | Route | Description |
|--------|-------|-------------|
| GET | `/` | List all lobbies |
| GET/POST | `/create` | Create new lobby |
| GET | `/<id>` | Lobby detail (main game UI) |
| POST | `/<id>/join` | Join a waiting lobby |
| POST | `/<id>/leave` | Leave (only if not locked) |
| POST | `/<id>/lock` | Lock lobby, start game |
| POST | `/<id>/edit` | Edit max_players |
| POST | `/<id>/note` | Save player note |
| POST | `/<id>/note/delete` | Delete a note |
| POST | `/<id>/chat` | Post chat message |
| GET | `/<id>/messages` | Poll chat messages (AJAX) |
| GET | `/<id>/state` | Get game state JSON (AJAX) |
| POST | `/<id>/reorder` | Reorder players (pre-lock only) |

### Savegame Blueprint
| Method | Route | Description |
|--------|-------|-------------|
| POST | `/upload/<id>` | Upload savegame (advances turn) |
| GET | `/download/<id>` | Download latest savegame |

---

## Game Flow

```
Register/Login
     │
     ▼
Create Lobby ──► Set max_players, name
     │
     ▼
Players Join (status: "waiting")
     │
Owner reorders players (optional)
     │
Owner Locks Lobby ──► status becomes "active", turn index = 0
     │
     ▼
Turn Loop:
  Current player downloads savegame
     │
  Plays locally (Civ IV, etc.)
     │
  Uploads new savegame + optional notes
     │
  Server advances current_turn_index
  Email notification sent to next player (if SMTP configured)
     │
  ▼ (repeat for all players)
     │
Owner marks game "finished"
```

---

## Configuration (`app/config.py`)

| Variable | Default | Purpose |
|----------|---------|---------|
| `SECRET_KEY` | Auto-generated 64-byte hex | Flask session encryption |
| `DATABASE_URL` | `sqlite:///instance/pbem.db` | DB connection (env var for prod) |
| `UPLOAD_FOLDER` | `./uploads` | Savegame file storage |
| `MAX_CONTENT_LENGTH` | 64 MB | Max upload size |

**PostgreSQL Note:** The config rewrites `postgres://` → `postgresql://` automatically for SQLAlchemy 1.4+ compatibility.

### Optional Email (server/ only)
| Variable | Purpose |
|----------|---------|
| `SMTP_HOST` | SMTP server hostname |
| `SMTP_PORT` | SMTP port (default 587) |
| `SMTP_USER` | Login username |
| `SMTP_PASS` | Login password |
| `SMTP_FROM` | Sender address (defaults to SMTP_USER) |

---

## Running the Application

### Development
```bash
# Install dependencies
pip install -r requirements.txt

# Run development server (auto-reloads)
python run.py
```

### Production
```bash
gunicorn run:app --bind 0.0.0.0:$PORT --workers 1 --threads 4
```

### Legacy REST API (server/)
```bash
pip install -r server/requirements.txt
python server/init_db.py   # Initialize DB schema
python server/app.py
```

### CLI Client (client/)
```bash
pip install -r client/requirements.txt
python client/pbem_client.py --help

# Example commands:
python client/pbem_client.py register
python client/pbem_client.py login
python client/pbem_client.py games
python client/pbem_client.py download <game_id>
python client/pbem_client.py endturn <game_id> savegame.civ4save
```

CLI stores auth token in `~/.pbem_client.json`. Default server: `http://localhost:5000`.

---

## Frontend Conventions

- **No JavaScript framework** — vanilla JS with `fetch()` for AJAX calls
- **Polling** — chat messages polled via `GET /<id>/messages` every few seconds
- **CSS aesthetic** — cyberpunk/retro terminal style with purple grid animation (defined in `base.html`)
- **Brand name** — use `STRAT//COM` in UI text (not "PBEM")
- **Chat culling** — keep only the 100 newest messages in the DOM to avoid memory bloat
- **Auto-scroll** — chat scrolls to bottom on page load and on new messages

---

## Database Conventions

- **SQLite WAL mode** enabled in development (set in `app/__init__.py` via PRAGMA)
- **Foreign keys** enforced via `PRAGMA foreign_keys = ON`
- **Migrations:** No migration framework (e.g., Flask-Migrate) is set up. Schema changes require manual `db.drop_all()` + `db.create_all()` or raw SQL during development.
- **Production:** Use `DATABASE_URL` env var pointing to a PostgreSQL instance.

---

## Code Conventions

- **App factory pattern** — `create_app()` in `app/__init__.py`; do not use global `app` object
- **Blueprints** — routes organized into `auth`, `lobby`, `savegame` blueprints; register new route groups as blueprints
- **Authentication** — session-based via `session['user_id']`; the `@login_required` decorator is defined in `app/__init__.py`
- **File uploads** — use `werkzeug.utils.secure_filename`; store in `app.config['UPLOAD_FOLDER']`
- **No test suite** — no formal tests exist; verify changes manually by running the app
- **No linter config** — no flake8/pylint/black configured; follow PEP 8 style conventions

---

## Deployment (Railway.app)

- Config: `railway.toml`
- Builder: NIXPACKS (auto-detects Python)
- Health check: `GET /` (must return 200)
- Restart policy: `ON_FAILURE`, max 10 retries
- Set `DATABASE_URL`, `SECRET_KEY` as Railway environment variables

---

## Key Caveats for AI Assistants

1. **Two separate Flask apps exist** — `app/` (web UI, active) and `server/` (legacy REST API). They do not share code or databases. When making changes, confirm which one is in scope.

2. **No migration tool** — adding columns or renaming models requires care. In dev, `db.create_all()` can be re-run; in prod, manual SQL or schema recreation is needed.

3. **Chat is polled, not WebSocket** — the chat system uses interval polling (`GET /<id>/messages`), not WebSockets. Do not introduce async frameworks unless explicitly requested.

   **IMPORTANT — chat poll must stay active when the tab is hidden.** In `detail.html`, the chat `poll()` function intentionally runs on its own `setInterval` *without* a `document.visibilityState` guard. This is by design so that users receive chat notifications (sound + unread badge) even when they have switched tabs. Do **not** add a visibility check to `poll()` or merge it back into the shared state interval. The state poll (`pollState()`) may remain visibility-gated since it only updates visual game-state elements.

4. **Savegame files on disk** — files are stored in the `uploads/` directory on the server filesystem. Cloud deployments (Railway ephemeral) should use external object storage if persistence is required.

5. **The CLI client targets the legacy `server/` API**, not the `app/` blueprints. The two have different endpoints and auth mechanisms (token vs. session).

6. **No automated tests** — always test changes manually by running `python run.py` and exercising the affected workflows in a browser.
