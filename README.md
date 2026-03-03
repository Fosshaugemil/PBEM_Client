# PBEM — Play By Email Server & Client

A lightweight prototype for running asynchronous (PBEM) game sessions.
Players take turns in a defined order; when you end your turn the savegame
is stored on the server and the next player is notified automatically.

## Architecture

```
server/
  app.py          Flask REST API + SQLite database
  init_db.py      One-shot DB initializer
  savegames/      Uploaded savegame files (auto-created)
  pbem.db         SQLite database (auto-created)

client/
  pbem_client.py  CLI client
```

---

## Quick Start

### 1 — Install dependencies

**Server**
```bash
cd server
pip install -r requirements.txt
```

**Client** (can be on a different machine)
```bash
cd client
pip install -r requirements.txt
```

### 2 — Start the server

```bash
cd server
python app.py
```

The server listens on `http://localhost:5000` by default.
Set `PORT=8080` to change the port.

### 3 — Register users & play

All commands below use the CLI client. Token is cached in `~/.pbem_client.json`.

```bash
# Point at the server (saved in config)
python client/pbem_client.py --server http://localhost:5000 register alice s3cr3t alice@example.com
python client/pbem_client.py login alice s3cr3t

# Create a game
python client/pbem_client.py create "Civ4 campaign" --desc "Epic marathon speed" --max-players 4

# Other players join (on their machines, pointing at the same server)
python client/pbem_client.py register bob hunter2
python client/pbem_client.py join 1

# Creator starts the game
python client/pbem_client.py start 1

# First player: end turn (uploads savegame, notifies next player)
python client/pbem_client.py endturn 1 ./mysave.civ4 --notes "Settled second city"

# Next player: download savegame, play, end turn
python client/pbem_client.py download 1
python client/pbem_client.py endturn 1 ./mysave.civ4 --notes "Built library"

# See who's been playing
python client/pbem_client.py history 1
```

---

## REST API Reference

All endpoints except `/api/register` and `/api/login` require
`Authorization: Bearer <token>` header.

### Auth

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/register` | `{username, password, email?}` → `{token, username}` |
| POST | `/api/login` | `{username, password}` → `{token, username}` |
| POST | `/api/logout` | Invalidate token |
| GET  | `/api/me` | Current user info |

### Games

| Method | Path | Description |
|--------|------|-------------|
| GET  | `/api/games[?status=waiting\|active\|finished]` | List games |
| POST | `/api/games` | `{name, description?, max_players?}` — Create game |
| GET  | `/api/games/<id>` | Game detail + player list + current player |
| POST | `/api/games/<id>/join` | Join a waiting game |
| POST | `/api/games/<id>/start` | Start (creator only, ≥2 players) |
| POST | `/api/games/<id>/leave` | Leave a waiting game |
| POST | `/api/games/<id>/finish` | Mark finished (creator only) |

### Turns & Savegames

| Method | Path | Description |
|--------|------|-------------|
| GET  | `/api/games/<id>/savegame` | Download latest savegame (players only) |
| POST | `/api/games/<id>/endturn` | Multipart: `file=<savegame>`, `notes=<text>` — end your turn |
| GET  | `/api/games/<id>/history` | Turn history |

---

## Game Flow

```
Creator registers → Creates game → Others join
       ↓
Creator calls /start → Status changes to "active", first player notified
       ↓
Current player downloads savegame → plays locally → calls /endturn (uploads file)
       ↓
Server stores savegame, advances turn index, emails next player
       ↓
Repeat until creator calls /finish
```

---

## Email Notifications (optional)

Set these environment variables before starting the server to enable SMTP notifications:

```bash
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASS=app-password
SMTP_FROM=you@gmail.com
```

If not configured, the server works fine — players just check manually.

---

## Configuration

| Env Var | Default | Description |
|---------|---------|-------------|
| `PORT` | `5000` | Server listen port |
| `PBEM_DB` | `pbem.db` | SQLite database path |
| `PBEM_SAVEGAME_DIR` | `savegames` | Where savegames are stored |
| `SMTP_HOST` | *(unset)* | SMTP server hostname |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USER` | *(unset)* | SMTP login |
| `SMTP_PASS` | *(unset)* | SMTP password |
| `SMTP_FROM` | `SMTP_USER` | From address in emails |
