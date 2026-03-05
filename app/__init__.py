import os
import sqlite3
from functools import wraps

from flask import Flask, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import joinedload

db = SQLAlchemy()
csrf = CSRFProtect()


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated


@event.listens_for(Engine, 'connect')
def set_sqlite_pragma(dbapi_conn, _):
    if isinstance(dbapi_conn, sqlite3.Connection):
        dbapi_conn.execute('PRAGMA foreign_keys=ON')
        dbapi_conn.execute('PRAGMA journal_mode=WAL')


def create_app(config_object='app.config.Config'):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object)

    db.init_app(app)
    csrf.init_app(app)

    with app.app_context():
        from . import models  # noqa: F401 — ensure models are registered before create_all
        db.create_all()
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    from .auth.routes import auth_bp
    from .lobby.routes import lobby_bp
    from .savegame.routes import savegame_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(lobby_bp, url_prefix='/lobbies')
    app.register_blueprint(savegame_bp, url_prefix='/savegames')

    @app.context_processor
    def inject_lobby_ribbon():
        if 'user_id' not in session:
            return {}
        from .models import ChatMessage, Lobby, LobbyMember
        memberships = db.session.execute(
            select(LobbyMember)
            .filter_by(user_id=session['user_id'])
            .options(joinedload(LobbyMember.lobby).joinedload(Lobby.members))
        ).unique().scalars().all()
        lobby_ids = [m.lobby_id for m in memberships]
        latest_msgs = {}
        if lobby_ids:
            latest_msgs = dict(db.session.execute(
                select(ChatMessage.lobby_id, func.max(ChatMessage.created_at).label('latest'))
                .where(ChatMessage.lobby_id.in_(lobby_ids))
                .group_by(ChatMessage.lobby_id)
            ).all())
        ribbon = []
        for m in memberships:
            lob = m.lobby
            is_my_turn = (
                lob.is_locked
                and lob.current_member is not None
                and lob.current_member.user_id == session['user_id']
            )
            ribbon.append({'lobby': lob, 'is_my_turn': is_my_turn,
                           'latest_msg_at': latest_msgs.get(lob.id)})
        ribbon.sort(key=lambda x: x['lobby'].created_at)
        return {'lobby_ribbon': ribbon}

    @app.route('/')
    def index():
        if 'user_id' in session:
            return redirect(url_for('lobby.list_lobbies'))
        return redirect(url_for('auth.login'))

    return app
