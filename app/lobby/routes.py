import os

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, abort, current_app, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

from datetime import datetime, timezone
from sqlalchemy import select

from .. import db, login_required
from ..models import ChatMessage, Lobby, LobbyMember, PlayerNote, SavegameFile, User
from ..savegame.validators import GAME_VALIDATORS, GAME_DISPLAY_NAMES

lobby_bp = Blueprint('lobby', __name__)


def _is_member(lobby_id, user_id):
    return db.session.execute(
        select(LobbyMember).filter_by(lobby_id=lobby_id, user_id=user_id)
    ).scalar_one_or_none() is not None


@lobby_bp.route('/')
@login_required
def list_lobbies():
    filt = request.args.get('filter', 'open')  # 'open' | 'mine' | 'all'

    user_lobby_ids = {m.lobby_id for m in db.session.execute(
        select(LobbyMember).filter_by(user_id=session['user_id'])
    ).scalars().all()}

    stmt = select(Lobby).order_by(Lobby.created_at.desc())
    if filt == 'open':
        stmt = stmt.where(Lobby.is_locked == False, Lobby.is_archived == False)  # noqa: E712
    elif filt == 'mine':
        stmt = stmt.where(Lobby.id.in_(user_lobby_ids))

    lobbies = db.session.execute(stmt).scalars().all()
    return render_template(
        'lobby/list.html',
        lobbies=lobbies,
        user_lobby_ids=user_lobby_ids,
        active_filter=filt,
        game_display_names=GAME_DISPLAY_NAMES,
    )


@lobby_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        max_players = request.form.get('max_players', '4')
        password = request.form.get('password', '')
        game_type = request.form.get('game_type', '').strip() or None
        if game_type and game_type not in GAME_VALIDATORS:
            game_type = None

        if not name:
            flash('Lobby name is required.')
            return render_template('lobby/create.html', game_display_names=GAME_DISPLAY_NAMES)

        try:
            max_players = int(max_players)
            if max_players < 2:
                raise ValueError
        except ValueError:
            flash('Max players must be a number >= 2.')
            return render_template('lobby/create.html', game_display_names=GAME_DISPLAY_NAMES)

        lobby = Lobby(
            name=name,
            description=description,
            max_players=max_players,
            owner_id=session['user_id'],
            password_hash=generate_password_hash(password) if password else None,
            game_type=game_type,
        )
        db.session.add(lobby)
        db.session.flush()  # get lobby.id before commit

        member = LobbyMember(lobby_id=lobby.id, user_id=session['user_id'])
        db.session.add(member)
        db.session.commit()
        return redirect(url_for('lobby.detail', lobby_id=lobby.id))

    return render_template('lobby/create.html', game_display_names=GAME_DISPLAY_NAMES)


@lobby_bp.route('/<int:lobby_id>')
@login_required
def detail(lobby_id):
    lobby = db.get_or_404(Lobby, lobby_id)
    if not _is_member(lobby_id, session['user_id']):
        flash('You must join this lobby first.')
        return redirect(url_for('lobby.list_lobbies'))
    savegames = db.session.execute(
        select(SavegameFile).filter_by(lobby_id=lobby_id)
        .order_by(SavegameFile.uploaded_at.desc())
    ).scalars().all()
    general_note = db.session.execute(
        select(PlayerNote).filter_by(
            user_id=session['user_id'], lobby_id=lobby_id, round_number=None)
    ).scalar_one_or_none()
    round_notes = db.session.execute(
        select(PlayerNote)
        .where(PlayerNote.user_id == session['user_id'],
               PlayerNote.lobby_id == lobby_id,
               PlayerNote.round_number.isnot(None))
        .order_by(PlayerNote.round_number.desc())
    ).scalars().all()
    chat_messages = list(reversed(
        db.session.execute(
            select(ChatMessage).filter_by(lobby_id=lobby_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(100)
        ).scalars().all()
    ))
    return render_template('lobby/detail.html', lobby=lobby, savegames=savegames,
                           general_note=general_note, round_notes=round_notes,
                           chat_messages=chat_messages,
                           game_display_names=GAME_DISPLAY_NAMES)


@lobby_bp.route('/<int:lobby_id>/join', methods=['POST'])
@login_required
def join(lobby_id):
    lobby = db.get_or_404(Lobby, lobby_id)

    if _is_member(lobby_id, session['user_id']):
        return redirect(url_for('lobby.detail', lobby_id=lobby_id))

    if lobby.is_locked:
        flash('This lobby is locked and no longer accepting players.')
        return redirect(url_for('lobby.list_lobbies'))

    if lobby.player_count >= lobby.max_players:
        flash('Lobby is full.')
        return redirect(url_for('lobby.list_lobbies'))

    if lobby.is_password_protected:
        password = request.form.get('password', '')
        if not check_password_hash(lobby.password_hash, password):
            flash('Wrong lobby password.')
            return redirect(url_for('lobby.list_lobbies'))

    member = LobbyMember(lobby_id=lobby_id, user_id=session['user_id'])
    db.session.add(member)
    db.session.commit()
    return redirect(url_for('lobby.detail', lobby_id=lobby_id))


@lobby_bp.route('/<int:lobby_id>/leave', methods=['POST'])
@login_required
def leave(lobby_id):
    lobby = db.get_or_404(Lobby, lobby_id)

    if lobby.owner_id == session['user_id']:
        flash('Owners cannot leave — delete the lobby instead.')
        return redirect(url_for('lobby.detail', lobby_id=lobby_id))

    if lobby.is_locked:
        flash('Cannot leave while the game is in progress.')
        return redirect(url_for('lobby.detail', lobby_id=lobby_id))

    member = db.session.execute(
        select(LobbyMember).filter_by(lobby_id=lobby_id, user_id=session['user_id'])
    ).scalar_one_or_none()
    if member:
        db.session.delete(member)
        db.session.commit()
    return redirect(url_for('lobby.list_lobbies'))


@lobby_bp.route('/<int:lobby_id>/edit', methods=['POST'])
@login_required
def edit(lobby_id):
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    lobby = db.get_or_404(Lobby, lobby_id)
    if lobby.owner_id != session['user_id']:
        abort(403)
    if lobby.is_locked:
        if is_ajax:
            return jsonify({'ok': False, 'error': 'Unlock the lobby before changing player limit.'}), 400
        flash('Unlock the lobby before changing player limit.')
        return redirect(url_for('lobby.detail', lobby_id=lobby_id))
    try:
        new_max = int(request.form.get('max_players', ''))
        if new_max < 2:
            raise ValueError
    except ValueError:
        if is_ajax:
            return jsonify({'ok': False, 'error': 'Player limit must be a number >= 2.'}), 400
        flash('Player limit must be a number >= 2.')
        return redirect(url_for('lobby.detail', lobby_id=lobby_id))
    if new_max < lobby.player_count:
        if is_ajax:
            return jsonify({'ok': False, 'error': f'Cannot set limit below current player count ({lobby.player_count}).'}), 400
        flash(f'Cannot set limit below current player count ({lobby.player_count}).')
        return redirect(url_for('lobby.detail', lobby_id=lobby_id))
    lobby.max_players = new_max
    db.session.commit()
    if is_ajax:
        return jsonify({'ok': True, 'max_players': lobby.max_players})
    flash('Player limit updated.')
    return redirect(url_for('lobby.detail', lobby_id=lobby_id))


@lobby_bp.route('/<int:lobby_id>/lock', methods=['POST'])
@login_required
def lock(lobby_id):
    lobby = db.get_or_404(Lobby, lobby_id)
    if lobby.owner_id != session['user_id']:
        abort(403)
    if lobby.is_locked:
        if lobby.has_started:
            flash('Cannot unlock a game once saves have been uploaded — this would corrupt turn order.')
            return redirect(url_for('lobby.detail', lobby_id=lobby_id))
        lobby.is_locked = False
        for m in lobby.members:
            m.play_order = None
        lobby.current_player_idx = 0
        lobby.current_round = 1
        db.session.commit()
        flash('Lobby unlocked — players can join again.')
    else:
        if lobby.player_count < lobby.max_players:
            flash(f'Lobby must be full before locking ({lobby.player_count}/{lobby.max_players} players).')
            return redirect(url_for('lobby.detail', lobby_id=lobby_id))
        lobby.is_locked = True
        members_with_order = [m for m in lobby.members if m.play_order is not None]
        if len(members_with_order) == len(lobby.members):
            pass  # owner pre-set the order via /reorder — keep it
        else:
            for i, m in enumerate(sorted(lobby.members, key=lambda m: m.joined_at)):
                m.play_order = i
        lobby.current_player_idx = 0
        lobby.current_round = 1
        db.session.commit()
        flash('Lobby locked. Game can begin!')
    return redirect(url_for('lobby.detail', lobby_id=lobby_id))


@lobby_bp.route('/<int:lobby_id>/note', methods=['POST'])
@login_required
def save_note(lobby_id):
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if not _is_member(lobby_id, session['user_id']):
        abort(403)
    content = request.form.get('content', '').strip()
    round_str = request.form.get('round_number', '').strip()
    round_number = None
    if round_str:
        try:
            round_number = int(round_str)
            if round_number < 1:
                raise ValueError
        except ValueError:
            if is_ajax:
                return jsonify({'ok': False, 'error': 'Round number must be a positive integer.'}), 400
            flash('Round number must be a positive integer.')
            return redirect(url_for('lobby.detail', lobby_id=lobby_id))
    if not content:
        if is_ajax:
            return jsonify({'ok': False, 'error': 'Note cannot be empty.'}), 400
        flash('Note cannot be empty.')
        return redirect(url_for('lobby.detail', lobby_id=lobby_id))
    existing = db.session.execute(
        select(PlayerNote).filter_by(
            user_id=session['user_id'], lobby_id=lobby_id, round_number=round_number)
    ).scalar_one_or_none()
    is_new = existing is None
    if existing:
        existing.content = content
        existing.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    else:
        db.session.add(PlayerNote(user_id=session['user_id'], lobby_id=lobby_id,
                                  round_number=round_number, content=content))
    db.session.commit()
    if is_ajax:
        return jsonify({'ok': True, 'is_new': is_new,
                        'round_number': round_number, 'content': content})
    flash('Note saved.')
    return redirect(url_for('lobby.detail', lobby_id=lobby_id))


@lobby_bp.route('/<int:lobby_id>/note/delete', methods=['POST'])
@login_required
def delete_note(lobby_id):
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if not _is_member(lobby_id, session['user_id']):
        abort(403)
    try:
        round_number = int(request.form.get('round_number', ''))
        if round_number < 1:
            raise ValueError
    except (ValueError, TypeError):
        if is_ajax:
            return jsonify({'ok': False, 'error': 'Invalid round number.'}), 400
        flash('Invalid round number.')
        return redirect(url_for('lobby.detail', lobby_id=lobby_id))
    note = db.session.execute(
        select(PlayerNote).filter_by(
            user_id=session['user_id'], lobby_id=lobby_id, round_number=round_number)
    ).scalar_one_or_none()
    if note:
        db.session.delete(note)
        db.session.commit()
    if is_ajax:
        return jsonify({'ok': True, 'round_number': round_number})
    flash('Round note deleted.')
    return redirect(url_for('lobby.detail', lobby_id=lobby_id))


@lobby_bp.route('/<int:lobby_id>/chat', methods=['POST'])
@login_required
def post_chat(lobby_id):
    if not _is_member(lobby_id, session['user_id']):
        abort(403)
    content = request.form.get('content', '').strip()[:1000]
    if not content:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'ok': False, 'error': 'empty'}), 400
        return redirect(url_for('lobby.detail', lobby_id=lobby_id, _anchor='chat'))
    msg = ChatMessage(lobby_id=lobby_id, user_id=session['user_id'], content=content)
    db.session.add(msg)
    db.session.commit()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'ok': True, 'message': {
            'id': msg.id, 'user_id': msg.user_id, 'username': msg.user.username,
            'content': msg.content, 'created_at': msg.created_at.isoformat() + 'Z',
        }})
    return redirect(url_for('lobby.detail', lobby_id=lobby_id, _anchor='chat'))


@lobby_bp.route('/<int:lobby_id>/messages')
@login_required
def get_messages(lobby_id):
    if not _is_member(lobby_id, session['user_id']):
        abort(403)
    after_str = request.args.get('after', '').rstrip('Z').split('+')[0]
    stmt = (select(ChatMessage)
            .filter_by(lobby_id=lobby_id)
            .order_by(ChatMessage.created_at.asc()))
    if after_str:
        try:
            stmt = stmt.where(ChatMessage.created_at > datetime.fromisoformat(after_str))
        except ValueError:
            pass
    return jsonify({'messages': [{
        'id': m.id, 'user_id': m.user_id, 'username': m.user.username,
        'content': m.content, 'created_at': m.created_at.isoformat() + 'Z',
    } for m in db.session.execute(stmt.limit(50)).scalars().all()]})


@lobby_bp.route('/<int:lobby_id>/state')
@login_required
def get_state(lobby_id):
    if not _is_member(lobby_id, session['user_id']):
        abort(403)
    lobby = db.get_or_404(Lobby, lobby_id)
    cur = lobby.current_member
    savegames = db.session.execute(
        select(SavegameFile).filter_by(lobby_id=lobby_id)
        .order_by(SavegameFile.uploaded_at.desc())
    ).scalars().all()
    return jsonify({
        'current_round': lobby.current_round,
        'current_player_user_id': cur.user_id if cur else None,
        'current_player_username': cur.user.username if cur else None,
        'savegames': [{
            'id': sg.id,
            'round_number': sg.round_number,
            'original_name': sg.original_name,
            'uploader_username': sg.uploader.username,
            'note': sg.note or '',
            'uploaded_at': sg.uploaded_at.isoformat() + 'Z',
            'download_url': url_for('savegame.download', file_id=sg.id),
        } for sg in savegames],
    })


@lobby_bp.route('/<int:lobby_id>/reorder', methods=['POST'])
@login_required
def reorder(lobby_id):
    lobby = db.get_or_404(Lobby, lobby_id)
    if lobby.owner_id != session['user_id']:
        abort(403)
    if lobby.is_locked:
        return jsonify({'ok': False, 'error': 'Lobby is locked.'}), 400
    data = request.get_json(force=True, silent=True) or {}
    user_ids = data.get('order', [])
    member_map = {m.user_id: m for m in lobby.members}
    if set(user_ids) != set(member_map.keys()) or len(user_ids) != len(member_map):
        return jsonify({'ok': False, 'error': 'Invalid player list.'}), 400
    for i, uid in enumerate(user_ids):
        member_map[uid].play_order = i
    db.session.commit()
    return jsonify({'ok': True})


@lobby_bp.route('/chat-timestamps')
@login_required
def chat_timestamps():
    """Return latest chat message timestamp per lobby for the current user.

    Used by the ribbon to poll for unread indicators without a full page reload.
    Response: {"timestamps": {"<lobby_id>": "<iso_ts>Z", ...}}
    """
    from sqlalchemy import func
    from ..models import LobbyMember
    memberships = db.session.execute(
        select(LobbyMember).filter_by(user_id=session['user_id'])
    ).scalars().all()
    lobby_ids = [m.lobby_id for m in memberships]
    result = {}
    if lobby_ids:
        rows = db.session.execute(
            select(ChatMessage.lobby_id, func.max(ChatMessage.created_at).label('latest'))
            .where(ChatMessage.lobby_id.in_(lobby_ids))
            .group_by(ChatMessage.lobby_id)
        ).all()
        for lobby_id, latest in rows:
            if latest:
                result[str(lobby_id)] = latest.isoformat() + 'Z'
    return jsonify({'timestamps': result})


@lobby_bp.route('/<int:lobby_id>/delete', methods=['POST'])
@login_required
def delete(lobby_id):
    lobby = db.get_or_404(Lobby, lobby_id)

    if lobby.owner_id != session['user_id']:
        abort(403)

    # Remove savegame files from disk before deleting rows
    upload_folder = current_app.config['UPLOAD_FOLDER']
    for sg in lobby.savegames:
        path = os.path.join(upload_folder, sg.stored_name)
        if os.path.exists(path):
            os.remove(path)

    db.session.delete(lobby)
    db.session.commit()
    flash(f'Lobby "{lobby.name}" deleted.')
    return redirect(url_for('lobby.list_lobbies'))


@lobby_bp.route('/<int:lobby_id>/archive', methods=['POST'])
@login_required
def archive(lobby_id):
    lobby = db.get_or_404(Lobby, lobby_id)
    if lobby.owner_id != session['user_id']:
        abort(403)
    lobby.is_archived = not lobby.is_archived
    db.session.commit()
    action = 'archived' if lobby.is_archived else 'unarchived'
    flash(f'Lobby "{lobby.name}" {action}.')
    return redirect(url_for('lobby.detail', lobby_id=lobby_id))
