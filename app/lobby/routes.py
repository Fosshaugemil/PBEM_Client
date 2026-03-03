import os

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, abort, current_app
from werkzeug.security import generate_password_hash, check_password_hash

from datetime import datetime

from .. import db, login_required
from ..models import ChatMessage, Lobby, LobbyMember, PlayerNote, SavegameFile, User

lobby_bp = Blueprint('lobby', __name__)


def _current_user():
    return User.query.get(session['user_id'])


def _is_member(lobby_id, user_id):
    return LobbyMember.query.filter_by(lobby_id=lobby_id, user_id=user_id).first() is not None


@lobby_bp.route('/')
@login_required
def list_lobbies():
    lobbies = Lobby.query.order_by(Lobby.created_at.desc()).all()
    user_lobby_ids = {m.lobby_id for m in LobbyMember.query.filter_by(user_id=session['user_id']).all()}
    return render_template('lobby/list.html', lobbies=lobbies, user_lobby_ids=user_lobby_ids)


@lobby_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        max_players = request.form.get('max_players', '4')
        password = request.form.get('password', '')

        if not name:
            flash('Lobby name is required.')
            return render_template('lobby/create.html')

        try:
            max_players = int(max_players)
            if max_players < 2:
                raise ValueError
        except ValueError:
            flash('Max players must be a number >= 2.')
            return render_template('lobby/create.html')

        lobby = Lobby(
            name=name,
            description=description,
            max_players=max_players,
            owner_id=session['user_id'],
            password_hash=generate_password_hash(password) if password else None,
        )
        db.session.add(lobby)
        db.session.flush()  # get lobby.id before commit

        member = LobbyMember(lobby_id=lobby.id, user_id=session['user_id'])
        db.session.add(member)
        db.session.commit()
        return redirect(url_for('lobby.detail', lobby_id=lobby.id))

    return render_template('lobby/create.html')


@lobby_bp.route('/<int:lobby_id>')
@login_required
def detail(lobby_id):
    lobby = Lobby.query.get_or_404(lobby_id)
    if not _is_member(lobby_id, session['user_id']):
        flash('You must join this lobby first.')
        return redirect(url_for('lobby.list_lobbies'))
    savegames = SavegameFile.query.filter_by(lobby_id=lobby_id).order_by(SavegameFile.uploaded_at.desc()).all()
    general_note = PlayerNote.query.filter_by(
        user_id=session['user_id'], lobby_id=lobby_id, round_number=None).first()
    round_notes = (PlayerNote.query
                   .filter(PlayerNote.user_id == session['user_id'],
                           PlayerNote.lobby_id == lobby_id,
                           PlayerNote.round_number.isnot(None))
                   .order_by(PlayerNote.round_number.desc())
                   .limit(5).all())
    chat_messages = (ChatMessage.query
                     .filter_by(lobby_id=lobby_id)
                     .order_by(ChatMessage.created_at.asc())
                     .limit(100).all())
    return render_template('lobby/detail.html', lobby=lobby, savegames=savegames,
                           general_note=general_note, round_notes=round_notes,
                           chat_messages=chat_messages)


@lobby_bp.route('/<int:lobby_id>/join', methods=['POST'])
@login_required
def join(lobby_id):
    lobby = Lobby.query.get_or_404(lobby_id)

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
    lobby = Lobby.query.get_or_404(lobby_id)

    if lobby.owner_id == session['user_id']:
        flash('Owners cannot leave — delete the lobby instead.')
        return redirect(url_for('lobby.detail', lobby_id=lobby_id))

    member = LobbyMember.query.filter_by(lobby_id=lobby_id, user_id=session['user_id']).first()
    if member:
        db.session.delete(member)
        db.session.commit()
    return redirect(url_for('lobby.list_lobbies'))


@lobby_bp.route('/<int:lobby_id>/edit', methods=['POST'])
@login_required
def edit(lobby_id):
    lobby = Lobby.query.get_or_404(lobby_id)
    if lobby.owner_id != session['user_id']:
        abort(403)
    if lobby.is_locked:
        flash('Unlock the lobby before changing player limit.')
        return redirect(url_for('lobby.detail', lobby_id=lobby_id))
    try:
        new_max = int(request.form.get('max_players', ''))
        if new_max < 2:
            raise ValueError
    except ValueError:
        flash('Player limit must be a number >= 2.')
        return redirect(url_for('lobby.detail', lobby_id=lobby_id))
    if new_max < lobby.player_count:
        flash(f'Cannot set limit below current player count ({lobby.player_count}).')
        return redirect(url_for('lobby.detail', lobby_id=lobby_id))
    lobby.max_players = new_max
    db.session.commit()
    flash('Player limit updated.')
    return redirect(url_for('lobby.detail', lobby_id=lobby_id))


@lobby_bp.route('/<int:lobby_id>/lock', methods=['POST'])
@login_required
def lock(lobby_id):
    lobby = Lobby.query.get_or_404(lobby_id)
    if lobby.owner_id != session['user_id']:
        abort(403)
    if lobby.is_locked:
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
            flash('Round number must be a positive integer.')
            return redirect(url_for('lobby.detail', lobby_id=lobby_id))
    if not content:
        flash('Note cannot be empty.')
        return redirect(url_for('lobby.detail', lobby_id=lobby_id))
    note = PlayerNote.query.filter_by(
        user_id=session['user_id'], lobby_id=lobby_id, round_number=round_number).first()
    if note:
        note.content = content
        note.updated_at = datetime.utcnow()
    else:
        note = PlayerNote(user_id=session['user_id'], lobby_id=lobby_id,
                          round_number=round_number, content=content)
        db.session.add(note)
    db.session.commit()
    flash('Note saved.')
    return redirect(url_for('lobby.detail', lobby_id=lobby_id))


@lobby_bp.route('/<int:lobby_id>/chat', methods=['POST'])
@login_required
def post_chat(lobby_id):
    if not _is_member(lobby_id, session['user_id']):
        abort(403)
    content = request.form.get('content', '').strip()[:1000]
    if content:
        msg = ChatMessage(lobby_id=lobby_id, user_id=session['user_id'], content=content)
        db.session.add(msg)
        db.session.commit()
    return redirect(url_for('lobby.detail', lobby_id=lobby_id, _anchor='chat'))


@lobby_bp.route('/<int:lobby_id>/delete', methods=['POST'])
@login_required
def delete(lobby_id):
    lobby = Lobby.query.get_or_404(lobby_id)

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
