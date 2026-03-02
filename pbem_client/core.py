from __future__ import annotations

import base64
import json
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


@dataclass
class Lobby:
    lobby_id: str
    players: list[str]
    current_turn_index: int = 0
    turn_number: int = 1

    @property
    def current_player(self) -> str:
        return self.players[self.current_turn_index]

    @property
    def next_player(self) -> str:
        return self.players[(self.current_turn_index + 1) % len(self.players)]


@dataclass
class TurnPacket:
    packet_id: str
    lobby_id: str
    turn_number: int
    from_player: str
    to_player: str
    created_at: float
    savefile_name: str
    savefile_b64: str


@dataclass
class PBEMState:
    player_id: str
    transport_dir: Optional[str] = None
    lobby: Optional[Lobby] = None
    inbox_seen_packet_ids: list[str] = None
    latest_savefile_name: Optional[str] = None

    def __post_init__(self) -> None:
        if self.inbox_seen_packet_ids is None:
            self.inbox_seen_packet_ids = []


class PBEMError(Exception):
    pass


def load_state(path: Path) -> PBEMState:
    data = json.loads(path.read_text())
    lobby = Lobby(**data["lobby"]) if data.get("lobby") else None
    return PBEMState(
        player_id=data["player_id"],
        transport_dir=data.get("transport_dir"),
        lobby=lobby,
        inbox_seen_packet_ids=data.get("inbox_seen_packet_ids", []),
        latest_savefile_name=data.get("latest_savefile_name"),
    )


def save_state(path: Path, state: PBEMState) -> None:
    payload = asdict(state)
    path.write_text(json.dumps(payload, indent=2))


def create_lobby(state: PBEMState, lobby_id: str, players: list[str], transport_dir: str) -> None:
    if len(players) < 2:
        raise PBEMError("Lobby requires at least 2 players")
    if len(players) != len(set(players)):
        raise PBEMError("Lobby players must be unique")
    if state.player_id not in players:
        raise PBEMError("Current player must be included in lobby players")

    state.lobby = Lobby(lobby_id=lobby_id, players=players)
    state.transport_dir = transport_dir
    Path(transport_dir).mkdir(parents=True, exist_ok=True)


def submit_turn(state: PBEMState, savefile: Path) -> TurnPacket:
    if state.lobby is None:
        raise PBEMError("No lobby configured")
    if not state.transport_dir:
        raise PBEMError("No transport directory configured")
    if state.lobby.current_player != state.player_id:
        raise PBEMError(f"Not your turn. Current player is {state.lobby.current_player}")

    save_bytes = savefile.read_bytes()
    packet = TurnPacket(
        packet_id=str(uuid.uuid4()),
        lobby_id=state.lobby.lobby_id,
        turn_number=state.lobby.turn_number,
        from_player=state.player_id,
        to_player=state.lobby.next_player,
        created_at=time.time(),
        savefile_name=savefile.name,
        savefile_b64=base64.b64encode(save_bytes).decode("ascii"),
    )

    out_path = Path(state.transport_dir) / f"{packet.packet_id}.json"
    out_path.write_text(json.dumps(asdict(packet), indent=2))

    state.lobby.current_turn_index = (state.lobby.current_turn_index + 1) % len(state.lobby.players)
    state.lobby.turn_number += 1
    state.latest_savefile_name = savefile.name
    return packet


def poll_packets(state: PBEMState, output_dir: Path) -> list[TurnPacket]:
    if state.lobby is None:
        raise PBEMError("No lobby configured")
    if not state.transport_dir:
        raise PBEMError("No transport directory configured")

    output_dir.mkdir(parents=True, exist_ok=True)
    packets: list[TurnPacket] = []
    for file in sorted(Path(state.transport_dir).glob("*.json")):
        raw = json.loads(file.read_text())
        packet = TurnPacket(**raw)
        if packet.packet_id in state.inbox_seen_packet_ids:
            continue
        if packet.to_player != state.player_id:
            continue
        if packet.lobby_id != state.lobby.lobby_id:
            continue

        save_bytes = base64.b64decode(packet.savefile_b64.encode("ascii"))
        destination = output_dir / packet.savefile_name
        destination.write_bytes(save_bytes)

        state.inbox_seen_packet_ids.append(packet.packet_id)
        state.latest_savefile_name = packet.savefile_name
        state.lobby.turn_number = packet.turn_number
        state.lobby.current_turn_index = state.lobby.players.index(state.player_id)
        packets.append(packet)
    return packets
