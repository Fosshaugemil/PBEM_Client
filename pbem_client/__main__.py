from __future__ import annotations

import argparse
import json
from pathlib import Path

from .core import PBEMError, PBEMState, Lobby, create_lobby, load_state, poll_packets, save_state, submit_turn


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PBEM peer-to-peer client")
    sub = parser.add_subparsers(dest="command", required=True)

    init_player = sub.add_parser("init-player")
    init_player.add_argument("--player-id", required=True)
    init_player.add_argument("--state", required=True)

    create = sub.add_parser("create-lobby")
    create.add_argument("--state", required=True)
    create.add_argument("--lobby-id", required=True)
    create.add_argument("--players", required=True, help="comma-separated ordered player ids")
    create.add_argument("--transport-dir", required=True)

    export_lobby = sub.add_parser("export-lobby")
    export_lobby.add_argument("--state", required=True)
    export_lobby.add_argument("--out", required=True)

    join = sub.add_parser("join-lobby")
    join.add_argument("--state", required=True)
    join.add_argument("--lobby-file", required=True)
    join.add_argument("--transport-dir", required=True)

    submit = sub.add_parser("submit-turn")
    submit.add_argument("--state", required=True)
    submit.add_argument("--save-file", required=True)

    poll = sub.add_parser("poll")
    poll.add_argument("--state", required=True)
    poll.add_argument("--output-dir", default="received_saves")

    show = sub.add_parser("show-state")
    show.add_argument("--state", required=True)

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    try:
        if args.command == "init-player":
            state = PBEMState(player_id=args.player_id)
            save_state(Path(args.state), state)
            print(f"Initialized player state: {args.state}")
            return

        state_path = Path(args.state)
        state = load_state(state_path)

        if args.command == "create-lobby":
            players = [p.strip() for p in args.players.split(",") if p.strip()]
            create_lobby(state, args.lobby_id, players, args.transport_dir)
            save_state(state_path, state)
            print(f"Lobby {args.lobby_id} created with players: {players}")
        elif args.command == "export-lobby":
            if state.lobby is None:
                raise PBEMError("No lobby configured")
            Path(args.out).write_text(json.dumps({"lobby": state.lobby.__dict__}, indent=2))
            print(f"Exported lobby to {args.out}")
        elif args.command == "join-lobby":
            payload = json.loads(Path(args.lobby_file).read_text())
            state.lobby = Lobby(**payload["lobby"])
            if state.player_id not in state.lobby.players:
                raise PBEMError("Player is not part of this lobby")
            state.transport_dir = args.transport_dir
            Path(state.transport_dir).mkdir(parents=True, exist_ok=True)
            save_state(state_path, state)
            print(f"Joined lobby {state.lobby.lobby_id}")
        elif args.command == "submit-turn":
            packet = submit_turn(state, Path(args.save_file))
            save_state(state_path, state)
            print(
                f"Turn {packet.turn_number} submitted by {packet.from_player}; "
                f"next player: {packet.to_player}"
            )
        elif args.command == "poll":
            packets = poll_packets(state, Path(args.output_dir))
            save_state(state_path, state)
            if not packets:
                print("No packets for you.")
            else:
                print(f"Received {len(packets)} packet(s). Latest save: {state.latest_savefile_name}")
        elif args.command == "show-state":
            print(
                json.dumps(
                    {
                        "player_id": state.player_id,
                        "transport_dir": state.transport_dir,
                        "latest_savefile_name": state.latest_savefile_name,
                        "inbox_seen_packet_ids": state.inbox_seen_packet_ids,
                        "lobby": state.lobby.__dict__ if state.lobby else None,
                    },
                    indent=2,
                )
            )
    except PBEMError as exc:
        raise SystemExit(f"Error: {exc}")


if __name__ == "__main__":
    main()
