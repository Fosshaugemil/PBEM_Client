"""
PBEM Server — Play By Email game coordination server.

Handles user accounts, game sessions, turn order, and savegame routing.
"""

import os
import sqlite3
import secrets
import smtplib
import mimetypes
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from functools import wraps
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, request, jsonify, g, send_from_directory

app = Flask(__name__)

DB_PATH = os.environ.get("PBEM_DB", "pbem.db")
SAVEGAME_DIR = Path(os.environ.get("PBEM_SAVEGAME_DIR", "savegames"))
SAVEGAME_DIR.mkdir(exist_ok=True)

# Optional SMTP config — set env vars to enable email notifications.
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER)


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT    NOT NULL UNIQUE,
    email       TEXT,
    password_hash TEXT  NOT NULL,
    created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS tokens (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    token       TEXT    NOT NULL UNIQUE,
    expires_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS games (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT    NOT NULL,
    description         TEXT    DEFAULT '',
    created_by          INTEGER NOT NULL REFERENCES users(id),
    status              TEXT    NOT NULL DEFAULT 'waiting',
    max_players         INTEGER NOT NULL DEFAULT 8,
    current_player_idx  INTEGER NOT NULL DEFAULT 0,
    turn_number         INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS game_players (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id     INTEGER NOT NULL REFERENCES games(id),
    user_id     INTEGER NOT NULL REFERENCES users(id),
    play_order  INTEGER NOT NULL,
    joined_at   TEXT    NOT NULL,
    UNIQUE(game_id, user_id),
    UNIQUE(game_id, play_order)
);

CREATE TABLE IF NOT EXISTS turns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id         INTEGER NOT NULL REFERENCES games(id),
    turn_number     INTEGER NOT NULL,
    player_id       INTEGER NOT NULL REFERENCES users(id),
    savegame_path   TEXT    NOT NULL,
    notes           TEXT    DEFAULT '',
    submitted_at    TEXT    NOT NULL
);
"""


def get_db():
    if "db" not in g:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _now():
    return datetime.utcnow().isoformat()


def create_token(user_id):
    token = secrets.token_hex(32)
    expires = (datetime.utcnow() + timedelta(days=30)).isoformat()
    db = get_db()
    db.execute(
        "INSERT INTO tokens (user_id, token, expires_at) VALUES (?,?,?)",
        (user_id, token, expires),
    )
    db.commit()
    return token


def resolve_token(token):
    """Return user row if token is valid, else None."""
    db = get_db()
    row = db.execute(
        """SELECT u.* FROM users u
           JOIN tokens t ON t.user_id = u.id
           WHERE t.token = ? AND t.expires_at > ?""",
        (token, _now()),
    ).fetchone()
    return row


def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        token = auth.removeprefix("Bearer ").strip()
        user = resolve_token(token) if token else None
        if not user:
            return jsonify({"error": "Unauthorized"}), 401
        g.current_user = user
        return f(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Email notification (optional)
# ---------------------------------------------------------------------------

def send_email(to_addr, subject, body):
    if not (SMTP_HOST and SMTP_USER and to_addr):
        return  # silently skip if not configured or recipient has no email
    try:
        msg = MIMEMultipart()
        msg["From"] = SMTP_FROM
        msg["To"] = to_addr
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_FROM, to_addr, msg.as_string())
    except Exception as exc:
        app.logger.warning("Email send failed: %s", exc)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def game_players_ordered(db, game_id):
    """Return list of player rows ordered by play_order."""
    return db.execute(
        """SELECT u.id, u.username, u.email, gp.play_order
           FROM game_players gp
           JOIN users u ON u.id = gp.user_id
           WHERE gp.game_id = ?
           ORDER BY gp.play_order""",
        (game_id,),
    ).fetchall()


def current_player(db, game):
    players = game_players_ordered(db, game["id"])
    if not players:
        return None
    idx = game["current_player_idx"] % len(players)
    return players[idx]


# ---------------------------------------------------------------------------
# Routes — Auth
# ---------------------------------------------------------------------------

@app.post("/api/register")
def register():
    data = request.get_json(force=True)
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    email = (data.get("email") or "").strip() or None

    if not username or not password:
        return jsonify({"error": "username and password required"}), 400
    if len(password) < 6:
        return jsonify({"error": "password must be at least 6 characters"}), 400

    db = get_db()
    existing = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    if existing:
        return jsonify({"error": "username already taken"}), 409

    pw_hash = generate_password_hash(password)
    cur = db.execute(
        "INSERT INTO users (username, email, password_hash, created_at) VALUES (?,?,?,?)",
        (username, email, pw_hash, _now()),
    )
    db.commit()
    token = create_token(cur.lastrowid)
    return jsonify({"token": token, "username": username}), 201


@app.post("/api/login")
def login():
    data = request.get_json(force=True)
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "invalid credentials"}), 401

    token = create_token(user["id"])
    return jsonify({"token": token, "username": user["username"]}), 200


@app.post("/api/logout")
@require_auth
def logout():
    auth = request.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    db = get_db()
    db.execute("DELETE FROM tokens WHERE token=?", (token,))
    db.commit()
    return jsonify({"ok": True})


@app.get("/api/me")
@require_auth
def me():
    u = g.current_user
    return jsonify({"id": u["id"], "username": u["username"], "email": u["email"]})


# ---------------------------------------------------------------------------
# Routes — Games
# ---------------------------------------------------------------------------

@app.get("/api/games")
@require_auth
def list_games():
    db = get_db()
    status_filter = request.args.get("status")  # waiting | active | finished
    if status_filter:
        rows = db.execute(
            "SELECT * FROM games WHERE status=? ORDER BY created_at DESC", (status_filter,)
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM games WHERE status != 'finished' ORDER BY created_at DESC"
        ).fetchall()

    result = []
    for g_row in rows:
        players = game_players_ordered(db, g_row["id"])
        result.append({
            "id": g_row["id"],
            "name": g_row["name"],
            "description": g_row["description"],
            "status": g_row["status"],
            "max_players": g_row["max_players"],
            "player_count": len(players),
            "turn_number": g_row["turn_number"],
            "created_at": g_row["created_at"],
        })
    return jsonify(result)


@app.post("/api/games")
@require_auth
def create_game():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()
    max_players = int(data.get("max_players") or 8)

    if not name:
        return jsonify({"error": "name required"}), 400
    if max_players < 2:
        return jsonify({"error": "max_players must be >= 2"}), 400

    db = get_db()
    user = g.current_user
    cur = db.execute(
        "INSERT INTO games (name, description, created_by, max_players, created_at) VALUES (?,?,?,?,?)",
        (name, description, user["id"], max_players, _now()),
    )
    game_id = cur.lastrowid
    # Creator auto-joins at position 0
    db.execute(
        "INSERT INTO game_players (game_id, user_id, play_order, joined_at) VALUES (?,?,?,?)",
        (game_id, user["id"], 0, _now()),
    )
    db.commit()
    return jsonify({"id": game_id, "name": name}), 201


@app.get("/api/games/<int:game_id>")
@require_auth
def get_game(game_id):
    db = get_db()
    game = db.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
    if not game:
        return jsonify({"error": "game not found"}), 404

    players = game_players_ordered(db, game_id)
    cp = current_player(db, game)
    last_turn = db.execute(
        "SELECT * FROM turns WHERE game_id=? ORDER BY turn_number DESC LIMIT 1",
        (game_id,),
    ).fetchone()

    return jsonify({
        "id": game["id"],
        "name": game["name"],
        "description": game["description"],
        "status": game["status"],
        "max_players": game["max_players"],
        "turn_number": game["turn_number"],
        "current_player": {"id": cp["id"], "username": cp["username"]} if cp else None,
        "players": [
            {"id": p["id"], "username": p["username"], "play_order": p["play_order"]}
            for p in players
        ],
        "last_savegame_at": last_turn["submitted_at"] if last_turn else None,
        "created_at": game["created_at"],
    })


@app.post("/api/games/<int:game_id>/join")
@require_auth
def join_game(game_id):
    db = get_db()
    game = db.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
    if not game:
        return jsonify({"error": "game not found"}), 404
    if game["status"] != "waiting":
        return jsonify({"error": "game already started or finished"}), 409

    user = g.current_user
    existing = db.execute(
        "SELECT id FROM game_players WHERE game_id=? AND user_id=?", (game_id, user["id"])
    ).fetchone()
    if existing:
        return jsonify({"error": "already in this game"}), 409

    players = game_players_ordered(db, game_id)
    if len(players) >= game["max_players"]:
        return jsonify({"error": "game is full"}), 409

    next_order = max((p["play_order"] for p in players), default=-1) + 1
    db.execute(
        "INSERT INTO game_players (game_id, user_id, play_order, joined_at) VALUES (?,?,?,?)",
        (game_id, user["id"], next_order, _now()),
    )
    db.commit()
    return jsonify({"ok": True, "play_order": next_order})


@app.post("/api/games/<int:game_id>/start")
@require_auth
def start_game(game_id):
    db = get_db()
    game = db.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
    if not game:
        return jsonify({"error": "game not found"}), 404
    if game["created_by"] != g.current_user["id"]:
        return jsonify({"error": "only the game creator can start the game"}), 403
    if game["status"] != "waiting":
        return jsonify({"error": "game is not in waiting status"}), 409

    players = game_players_ordered(db, game_id)
    if len(players) < 2:
        return jsonify({"error": "need at least 2 players to start"}), 409

    db.execute("UPDATE games SET status='active', turn_number=1 WHERE id=?", (game_id,))
    db.commit()

    # Notify first player
    first = players[0]
    send_email(
        first["email"],
        f"[PBEM] {game['name']} — Your turn!",
        f"Hi {first['username']},\n\nThe game '{game['name']}' has started. It's your turn!\n"
        f"Log in to download the savegame and make your moves.\n",
    )
    return jsonify({"ok": True, "status": "active"})


@app.post("/api/games/<int:game_id>/leave")
@require_auth
def leave_game(game_id):
    db = get_db()
    game = db.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
    if not game:
        return jsonify({"error": "game not found"}), 404
    if game["status"] == "active":
        return jsonify({"error": "cannot leave an active game; ask the host to end it"}), 409

    user = g.current_user
    db.execute(
        "DELETE FROM game_players WHERE game_id=? AND user_id=?", (game_id, user["id"])
    )
    db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Routes — Savegames & Turns
# ---------------------------------------------------------------------------

@app.get("/api/games/<int:game_id>/savegame")
@require_auth
def download_savegame(game_id):
    db = get_db()
    game = db.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
    if not game:
        return jsonify({"error": "game not found"}), 404

    # Must be a player in the game
    user = g.current_user
    player_row = db.execute(
        "SELECT id FROM game_players WHERE game_id=? AND user_id=?",
        (game_id, user["id"]),
    ).fetchone()
    if not player_row:
        return jsonify({"error": "you are not in this game"}), 403

    last_turn = db.execute(
        "SELECT * FROM turns WHERE game_id=? ORDER BY turn_number DESC LIMIT 1",
        (game_id,),
    ).fetchone()
    if not last_turn:
        return jsonify({"error": "no savegame uploaded yet"}), 404

    savepath = Path(last_turn["savegame_path"])
    return send_from_directory(
        savepath.parent.resolve(),
        savepath.name,
        as_attachment=True,
        download_name=f"game{game_id}_turn{last_turn['turn_number']}{savepath.suffix}",
    )


@app.post("/api/games/<int:game_id>/endturn")
@require_auth
def end_turn(game_id):
    """
    Upload a savegame file and end your turn.

    Expects multipart/form-data with:
      - file: the savegame file
      - notes: optional text notes for this turn
    """
    db = get_db()
    game = db.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
    if not game:
        return jsonify({"error": "game not found"}), 404
    if game["status"] != "active":
        return jsonify({"error": "game is not active"}), 409

    user = g.current_user
    cp = current_player(db, game)
    if not cp or cp["id"] != user["id"]:
        return jsonify({"error": "it is not your turn"}), 403

    if "file" not in request.files:
        return jsonify({"error": "savegame file required (multipart field: 'file')"}), 400

    savefile = request.files["file"]
    notes = request.form.get("notes", "")

    # Persist savegame file
    game_dir = SAVEGAME_DIR / str(game_id)
    game_dir.mkdir(exist_ok=True)
    ext = Path(savefile.filename).suffix if savefile.filename else ".sav"
    turn_number = game["turn_number"]
    filename = f"turn_{turn_number:04d}_player_{user['id']}{ext}"
    save_path = game_dir / filename
    savefile.save(save_path)

    # Record turn in DB
    db.execute(
        "INSERT INTO turns (game_id, turn_number, player_id, savegame_path, notes, submitted_at)"
        " VALUES (?,?,?,?,?,?)",
        (game_id, turn_number, user["id"], str(save_path), notes, _now()),
    )

    # Advance to next player
    players = game_players_ordered(db, game_id)
    next_idx = (game["current_player_idx"] + 1) % len(players)
    new_turn_number = turn_number + 1

    db.execute(
        "UPDATE games SET current_player_idx=?, turn_number=? WHERE id=?",
        (next_idx, new_turn_number, game_id),
    )
    db.commit()

    next_player = players[next_idx]

    # Notify next player via email
    send_email(
        next_player["email"],
        f"[PBEM] {game['name']} — Your turn! (Turn {new_turn_number})",
        f"Hi {next_player['username']},\n\n"
        f"{user['username']} has finished their turn in '{game['name']}'.\n"
        f"It's now turn {new_turn_number} and it's your move!\n\n"
        f"Log in to download the savegame.\n"
        + (f"\nTurn notes: {notes}\n" if notes else ""),
    )

    return jsonify({
        "ok": True,
        "next_player": next_player["username"],
        "turn_number": new_turn_number,
    })


@app.get("/api/games/<int:game_id>/history")
@require_auth
def turn_history(game_id):
    db = get_db()
    game = db.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
    if not game:
        return jsonify({"error": "game not found"}), 404

    turns = db.execute(
        """SELECT t.turn_number, t.notes, t.submitted_at, u.username
           FROM turns t JOIN users u ON u.id = t.player_id
           WHERE t.game_id = ?
           ORDER BY t.turn_number""",
        (game_id,),
    ).fetchall()

    return jsonify([
        {
            "turn_number": t["turn_number"],
            "player": t["username"],
            "notes": t["notes"],
            "submitted_at": t["submitted_at"],
        }
        for t in turns
    ])


@app.post("/api/games/<int:game_id>/finish")
@require_auth
def finish_game(game_id):
    db = get_db()
    game = db.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
    if not game:
        return jsonify({"error": "game not found"}), 404
    if game["created_by"] != g.current_user["id"]:
        return jsonify({"error": "only the creator can finish the game"}), 403

    db.execute("UPDATE games SET status='finished' WHERE id=?", (game_id,))
    db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
