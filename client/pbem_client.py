#!/usr/bin/env python3
"""
PBEM CLI Client

Usage:
    pbem_client.py [--server URL] <command> [args...]

Commands:
    register <username> <password> [email]
    login    <username> <password>
    logout
    whoami

    games [--status waiting|active|finished]
    game   <id>
    create <name> [--desc TEXT] [--max-players N]
    join   <id>
    start  <id>
    leave  <id>
    finish <id>

    download <id> [output_file]
    endturn  <id> <savefile> [--notes TEXT]
    history  <id>
"""

import argparse
import json
import os
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("Install dependencies: pip install requests")
    sys.exit(1)

CONFIG_FILE = Path.home() / ".pbem_client.json"
DEFAULT_SERVER = "http://localhost:5000"


# ---------------------------------------------------------------------------
# Config helpers (token persistence)
# ---------------------------------------------------------------------------

def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}


def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)
    CONFIG_FILE.chmod(0o600)


def get_server(cfg, args):
    return getattr(args, "server", None) or cfg.get("server") or DEFAULT_SERVER


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def api(method, server, path, token=None, **kwargs):
    url = server.rstrip("/") + path
    headers = kwargs.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = getattr(requests, method)(url, headers=headers, **kwargs)
    return resp


def ok_or_exit(resp):
    """Print response JSON and exit on error."""
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text}
    if not resp.ok:
        print(f"Error {resp.status_code}: {data.get('error', data)}", file=sys.stderr)
        sys.exit(1)
    return data


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_register(args, cfg):
    server = get_server(cfg, args)
    payload = {"username": args.username, "password": args.password}
    if args.email:
        payload["email"] = args.email
    data = ok_or_exit(api("post", server, "/api/register", json=payload))
    cfg["token"] = data["token"]
    cfg["username"] = data["username"]
    cfg["server"] = server
    save_config(cfg)
    print(f"Registered and logged in as '{data['username']}'.")


def cmd_login(args, cfg):
    server = get_server(cfg, args)
    data = ok_or_exit(api("post", server, "/api/login",
                          json={"username": args.username, "password": args.password}))
    cfg["token"] = data["token"]
    cfg["username"] = data["username"]
    cfg["server"] = server
    save_config(cfg)
    print(f"Logged in as '{data['username']}'.")


def cmd_logout(args, cfg):
    server = get_server(cfg, args)
    token = cfg.get("token")
    if token:
        api("post", server, "/api/logout", token=token)
    cfg.pop("token", None)
    cfg.pop("username", None)
    save_config(cfg)
    print("Logged out.")


def cmd_whoami(args, cfg):
    server = get_server(cfg, args)
    token = cfg.get("token")
    data = ok_or_exit(api("get", server, "/api/me", token=token))
    print(f"  Username : {data['username']}")
    print(f"  Email    : {data.get('email') or '(none)'}")


def cmd_games(args, cfg):
    server = get_server(cfg, args)
    token = cfg.get("token")
    params = {}
    if hasattr(args, "status") and args.status:
        params["status"] = args.status
    data = ok_or_exit(api("get", server, "/api/games", token=token, params=params))
    if not data:
        print("No games found.")
        return
    print(f"{'ID':>4}  {'Name':<30}  {'Status':<10}  {'Players':>7}  {'Turn':>5}")
    print("-" * 65)
    for g in data:
        print(f"{g['id']:>4}  {g['name']:<30}  {g['status']:<10}  "
              f"{g['player_count']:>3}/{g['max_players']:<3}  {g['turn_number']:>5}")


def cmd_game(args, cfg):
    server = get_server(cfg, args)
    token = cfg.get("token")
    data = ok_or_exit(api("get", server, f"/api/games/{args.id}", token=token))
    cp = data.get("current_player")
    print(f"Game #{data['id']}: {data['name']}")
    print(f"  Description : {data['description'] or '(none)'}")
    print(f"  Status      : {data['status']}")
    print(f"  Turn        : {data['turn_number']}")
    print(f"  Current     : {cp['username'] if cp else '(none)'}")
    print(f"  Players     :")
    for p in data["players"]:
        marker = " <-- YOUR TURN" if cp and p["id"] == cp["id"] else ""
        print(f"    {p['play_order']+1}. {p['username']}{marker}")
    if data.get("last_savegame_at"):
        print(f"  Last upload : {data['last_savegame_at']}")


def cmd_create(args, cfg):
    server = get_server(cfg, args)
    token = cfg.get("token")
    payload = {
        "name": args.name,
        "description": getattr(args, "desc", "") or "",
        "max_players": getattr(args, "max_players", 8) or 8,
    }
    data = ok_or_exit(api("post", server, "/api/games", token=token, json=payload))
    print(f"Game created with ID {data['id']}. You have been added as player #1.")
    print("Have others join with:  pbem_client.py join " + str(data['id']))
    print("Then start with:        pbem_client.py start " + str(data['id']))


def cmd_join(args, cfg):
    server = get_server(cfg, args)
    token = cfg.get("token")
    data = ok_or_exit(api("post", server, f"/api/games/{args.id}/join", token=token))
    print(f"Joined game {args.id}. You are player #{data['play_order'] + 1}.")


def cmd_start(args, cfg):
    server = get_server(cfg, args)
    token = cfg.get("token")
    ok_or_exit(api("post", server, f"/api/games/{args.id}/start", token=token))
    print(f"Game {args.id} started! The first player has been notified.")


def cmd_leave(args, cfg):
    server = get_server(cfg, args)
    token = cfg.get("token")
    ok_or_exit(api("post", server, f"/api/games/{args.id}/leave", token=token))
    print(f"Left game {args.id}.")


def cmd_finish(args, cfg):
    server = get_server(cfg, args)
    token = cfg.get("token")
    ok_or_exit(api("post", server, f"/api/games/{args.id}/finish", token=token))
    print(f"Game {args.id} marked as finished.")


def cmd_download(args, cfg):
    server = get_server(cfg, args)
    token = cfg.get("token")
    resp = api("get", server, f"/api/games/{args.id}/savegame", token=token, stream=True)
    if not resp.ok:
        try:
            err = resp.json().get("error", resp.text)
        except Exception:
            err = resp.text
        print(f"Error {resp.status_code}: {err}", file=sys.stderr)
        sys.exit(1)

    # Determine output filename
    out = getattr(args, "output", None)
    if not out:
        cd = resp.headers.get("Content-Disposition", "")
        if "filename=" in cd:
            out = cd.split("filename=")[-1].strip('" ')
        else:
            out = f"game{args.id}_savegame.sav"
    with open(out, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    print(f"Savegame downloaded to '{out}'.")


def cmd_endturn(args, cfg):
    server = get_server(cfg, args)
    token = cfg.get("token")
    savefile = Path(args.savefile)
    if not savefile.exists():
        print(f"File not found: {savefile}", file=sys.stderr)
        sys.exit(1)

    with open(savefile, "rb") as f:
        files = {"file": (savefile.name, f)}
        data_form = {"notes": getattr(args, "notes", "") or ""}
        data = ok_or_exit(
            api("post", server, f"/api/games/{args.id}/endturn",
                token=token, files=files, data=data_form)
        )
    print(f"Turn submitted. Next player: {data['next_player']} (turn {data['turn_number']}).")


def cmd_history(args, cfg):
    server = get_server(cfg, args)
    token = cfg.get("token")
    data = ok_or_exit(api("get", server, f"/api/games/{args.id}/history", token=token))
    if not data:
        print("No turns played yet.")
        return
    print(f"{'Turn':>5}  {'Player':<20}  {'Submitted':<25}  Notes")
    print("-" * 75)
    for t in data:
        print(f"{t['turn_number']:>5}  {t['player']:<20}  {t['submitted_at']:<25}  {t['notes']}")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(
        prog="pbem_client.py",
        description="PBEM (Play By Email) game client",
    )
    p.add_argument("--server", metavar="URL", help=f"Server URL (default: {DEFAULT_SERVER})")
    sub = p.add_subparsers(dest="command", required=True)

    # Auth
    r = sub.add_parser("register", help="Create a new account")
    r.add_argument("username")
    r.add_argument("password")
    r.add_argument("email", nargs="?", default=None)

    lo = sub.add_parser("login", help="Log in")
    lo.add_argument("username")
    lo.add_argument("password")

    sub.add_parser("logout", help="Log out")
    sub.add_parser("whoami", help="Show current user")

    # Games
    gl = sub.add_parser("games", help="List games")
    gl.add_argument("--status", choices=["waiting", "active", "finished"])

    gg = sub.add_parser("game", help="Show game details")
    gg.add_argument("id", type=int)

    cr = sub.add_parser("create", help="Create a new game")
    cr.add_argument("name")
    cr.add_argument("--desc", default="")
    cr.add_argument("--max-players", type=int, default=8)

    jn = sub.add_parser("join", help="Join a game")
    jn.add_argument("id", type=int)

    st = sub.add_parser("start", help="Start a game (creator only)")
    st.add_argument("id", type=int)

    lv = sub.add_parser("leave", help="Leave a waiting game")
    lv.add_argument("id", type=int)

    fi = sub.add_parser("finish", help="Mark game as finished (creator only)")
    fi.add_argument("id", type=int)

    # Savegame
    dl = sub.add_parser("download", help="Download current savegame")
    dl.add_argument("id", type=int)
    dl.add_argument("output", nargs="?", default=None, help="Output filename")

    et = sub.add_parser("endturn", help="Upload savegame and end your turn")
    et.add_argument("id", type=int)
    et.add_argument("savefile", help="Path to savegame file")
    et.add_argument("--notes", default="", help="Optional turn notes")

    hi = sub.add_parser("history", help="Show turn history for a game")
    hi.add_argument("id", type=int)

    return p


COMMANDS = {
    "register": cmd_register,
    "login": cmd_login,
    "logout": cmd_logout,
    "whoami": cmd_whoami,
    "games": cmd_games,
    "game": cmd_game,
    "create": cmd_create,
    "join": cmd_join,
    "start": cmd_start,
    "leave": cmd_leave,
    "finish": cmd_finish,
    "download": cmd_download,
    "endturn": cmd_endturn,
    "history": cmd_history,
}


def main():
    parser = build_parser()
    args = parser.parse_args()
    cfg = load_config()

    cmd_fn = COMMANDS.get(args.command)
    if not cmd_fn:
        parser.print_help()
        sys.exit(1)
    cmd_fn(args, cfg)


if __name__ == "__main__":
    main()
