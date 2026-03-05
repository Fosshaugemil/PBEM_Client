import os
import uuid

from flask import Blueprint, request, redirect, url_for, session, flash, abort, current_app, jsonify
from flask import send_from_directory
from werkzeug.utils import secure_filename
from sqlalchemy import select

from .. import db, login_required
from ..models import Lobby, LobbyMember, SavegameFile, User
from .validators import GAME_VALIDATORS, validate_generic

_BLOCKED_EXTENSIONS = {'.exe', '.bat', '.cmd', '.sh', '.ps1', '.py', '.js', '.php', '.rb', '.dll', '.vbs'}

savegame_bp = Blueprint('savegame', __name__)


def _assert_member(lobby_id, user_id):
    if not db.session.execute(
        select(LobbyMember).filter_by(lobby_id=lobby_id, user_id=user_id)
    ).scalar_one_or_none():
        abort(403)


@savegame_bp.route('/upload/<int:lobby_id>', methods=['POST'])
@login_required
def upload(lobby_id):
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    lobby = db.get_or_404(Lobby, lobby_id)
    _assert_member(lobby_id, session['user_id'])

    if not lobby.is_locked:
        if is_ajax:
            return jsonify({'ok': False, 'error': 'Game has not started yet.'}), 400
        flash('Game has not started yet.')
        return redirect(url_for('lobby.detail', lobby_id=lobby_id))

    if lobby.current_member is None or lobby.current_member.user_id != session['user_id']:
        if is_ajax:
            return jsonify({'ok': False, 'error': 'It is not your turn.'}), 403
        flash('It is not your turn.')
        return redirect(url_for('lobby.detail', lobby_id=lobby_id))

    if 'savegame' not in request.files:
        if is_ajax:
            return jsonify({'ok': False, 'error': 'No file part in the request.'}), 400
        flash('No file part in the request.')
        return redirect(url_for('lobby.detail', lobby_id=lobby_id))

    f = request.files['savegame']
    if not f.filename:
        if is_ajax:
            return jsonify({'ok': False, 'error': 'No file selected.'}), 400
        flash('No file selected.')
        return redirect(url_for('lobby.detail', lobby_id=lobby_id))

    safe_name = secure_filename(f.filename)
    if not safe_name:
        if is_ajax:
            return jsonify({'ok': False, 'error': 'Invalid filename.'}), 400
        flash('Invalid filename.')
        return redirect(url_for('lobby.detail', lobby_id=lobby_id))

    ext = os.path.splitext(safe_name)[1].lower()
    if ext in _BLOCKED_EXTENSIONS:
        if is_ajax:
            return jsonify({'ok': False, 'error': 'File type not allowed.'}), 400
        flash('File type not allowed.')
        return redirect(url_for('lobby.detail', lobby_id=lobby_id))

    # Run game-specific savefile validation
    file_size = f.seek(0, 2) or 0
    f.seek(0)
    validator = GAME_VALIDATORS.get(lobby.game_type or 'generic', validate_generic)
    ok, err_msg = validator(f, safe_name, file_size)
    if not ok:
        if is_ajax:
            return jsonify({'ok': False, 'error': f'Save file rejected: {err_msg}'}), 400
        flash(f'Save file rejected: {err_msg}')
        return redirect(url_for('lobby.detail', lobby_id=lobby_id))

    stored_name = f"{uuid.uuid4().hex}_{safe_name}"
    upload_folder = current_app.config['UPLOAD_FOLDER']
    f.save(os.path.join(upload_folder, stored_name))

    note = request.form.get('note', '').strip()[:512]

    sg = SavegameFile(
        lobby_id=lobby_id,
        uploader_id=session['user_id'],
        original_name=f.filename[:256],
        stored_name=stored_name,
        round_number=lobby.current_round,
        note=note,
    )
    db.session.add(sg)

    # Advance the turn
    ordered = lobby.ordered_members
    new_idx = (lobby.current_player_idx + 1) % len(ordered)
    if new_idx == 0:
        lobby.current_round += 1
    lobby.current_player_idx = new_idx
    next_player = ordered[new_idx].user.username

    # Prune saves more than 2 rounds old (keep current + previous round)
    prune_before = lobby.current_round - 2
    if prune_before >= 1:
        old_saves = db.session.execute(
            select(SavegameFile).where(
                SavegameFile.lobby_id == lobby_id,
                SavegameFile.round_number <= prune_before,
            )
        ).scalars().all()
        for old in old_saves:
            path = os.path.join(upload_folder, old.stored_name)
            if os.path.exists(path):
                os.remove(path)
            db.session.delete(old)

    db.session.commit()

    if is_ajax:
        new_member = lobby.current_member
        uploader = db.session.get(User, session['user_id'])
        return jsonify({
            'ok': True,
            'message': f'Savegame uploaded. Turn passed to {next_player}.',
            'current_round': lobby.current_round,
            'current_player_username': new_member.user.username if new_member else None,
            'current_player_user_id': new_member.user_id if new_member else None,
            'is_my_turn_now': new_member is not None and new_member.user_id == session['user_id'],
            'savegame': {
                'id': sg.id,
                'original_name': sg.original_name,
                'note': sg.note or '',
                'uploader_username': uploader.username if uploader else '?',
                'uploaded_at': sg.uploaded_at.isoformat() + 'Z',
                'round_number': sg.round_number,
                'download_url': url_for('savegame.download', file_id=sg.id),
            },
        })

    flash(f'Savegame uploaded. Turn passed to {next_player}.')
    return redirect(url_for('lobby.detail', lobby_id=lobby_id))


@savegame_bp.route('/download/<int:file_id>')
@login_required
def download(file_id):
    sg = db.get_or_404(SavegameFile, file_id)
    _assert_member(sg.lobby_id, session['user_id'])

    upload_folder = current_app.config['UPLOAD_FOLDER']
    return send_from_directory(
        upload_folder,
        sg.stored_name,
        as_attachment=True,
        download_name=sg.original_name,
    )
