import os

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, abort, current_app
from werkzeug.security import generate_password_hash, check_password_hash

from .. import db, login_required
from ..models import Lobby, LobbyMember, SavegameFile, User

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
    return render_template('lobby/detail.html', lobby=lobby, savegames=savegames)


@lobby_bp.route('/<int:lobby_id>/join', methods=['POST'])
@login_required
def join(lobby_id):
    lobby = Lobby.query.get_or_404(lobby_id)

    if _is_member(lobby_id, session['user_id']):
        return redirect(url_for('lobby.detail', lobby_id=lobby_id))

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
