# PBEM Client (Peer-to-Peer Turn Relay)

This repository now contains a minimal, extensible PBEM client prototype focused on:

- **Peer-to-peer turn passing** (no central game server required)
- **Lobby setup** with fixed players + explicit turn order
- **Save file handoff** to the next player
- **Turn notifications** delivered as messages in a shared transport medium

## How it works

Each player runs the same CLI and keeps a local state file. A game has:

- A `lobby_id`
- Ordered `players`
- `current_turn_index`
- Monotonic `turn_number`

When a player submits a turn:

1. The client verifies it is that player's turn.
2. It wraps the save file in a `TurnPacket`.
3. It sends the packet to the **next player** via a pluggable transport.
4. The receiver imports it and becomes the active player.

### Transport model

The default transport is `filesystem`:

- Outgoing packets are written to a shared directory as JSON + base64 payload.
- Every player can poll that directory for messages addressed to them.

This is useful for PBEM-style async exchange over tools like Syncthing, shared folders, NAS, or mounted cloud storage.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
python -m pbem_client init-player --player-id alice --state alice.json
python -m pbem_client init-player --player-id bob --state bob.json

python -m pbem_client create-lobby \
  --state alice.json \
  --lobby-id demo \
  --players alice,bob \
  --transport-dir ./transport

python -m pbem_client show-state --state alice.json
```

Alice submits a turn:

```bash
python -m pbem_client submit-turn \
  --state alice.json \
  --save-file ./savegame_turn1.sav
```

Bob polls and imports his next turn:

```bash
python -m pbem_client poll --state bob.json
```

## Commands

- `init-player`: create a local player state file.
- `create-lobby`: define lobby players/order and start on turn 1.
- `join-lobby`: import a lobby from a JSON file (if distributed separately).
- `export-lobby`: write lobby definition JSON.
- `submit-turn`: send the current save file to the next player.
- `poll`: receive and import turn packets addressed to this player.
- `show-state`: print current local state.

## Notes for production hardening

This prototype is intentionally small and local-first. Next steps:

- Add packet signing (ed25519) and verification.
- Add packet encryption (recipient public keys).
- Add SMTP/IMAP transport adapter for actual email notifications.
- Add conflict handling/replay protection across devices.
- Add optional NAT traversal transport (e.g. WebRTC data channels) for direct online relay.
