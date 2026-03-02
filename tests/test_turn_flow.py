from pathlib import Path

from pbem_client.core import PBEMState, create_lobby, poll_packets, submit_turn


def test_turn_submission_and_poll(tmp_path: Path) -> None:
    transport = tmp_path / "transport"
    alice = PBEMState(player_id="alice")
    bob = PBEMState(player_id="bob")

    create_lobby(alice, lobby_id="demo", players=["alice", "bob"], transport_dir=str(transport))
    bob.lobby = alice.lobby
    bob.transport_dir = str(transport)

    save_file = tmp_path / "turn1.sav"
    save_file.write_bytes(b"hello-save")

    packet = submit_turn(alice, save_file)

    received = poll_packets(bob, tmp_path / "bob_saves")

    assert packet.to_player == "bob"
    assert len(received) == 1
    assert (tmp_path / "bob_saves" / "turn1.sav").read_bytes() == b"hello-save"
    assert bob.lobby.current_player == "bob"
