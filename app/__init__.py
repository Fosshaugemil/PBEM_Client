import os
import sqlite3
from functools import wraps

from flask import Flask, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.engine import Engine

db = SQLAlchemy()


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
        from .models import LobbyMember
        memberships = LobbyMember.query.filter_by(user_id=session['user_id']).all()
        ribbon = []
        for m in memberships:
            lob = m.lobby
            is_my_turn = (
                lob.is_locked
                and lob.current_member is not None
                and lob.current_member.user_id == session['user_id']
            )
            ribbon.append({'lobby': lob, 'is_my_turn': is_my_turn})
        ribbon.sort(key=lambda x: x['lobby'].created_at)
        return {'lobby_ribbon': ribbon}

    @app.route('/')
    def index():
        if 'user_id' in session:
            return redirect(url_for('lobby.list_lobbies'))
        return redirect(url_for('auth.login'))

    return app
