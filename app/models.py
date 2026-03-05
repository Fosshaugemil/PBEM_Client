from datetime import datetime, timezone
from . import db


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=_utcnow)

    memberships = db.relationship('LobbyMember', back_populates='user', cascade='all, delete-orphan')
    uploads = db.relationship('SavegameFile', back_populates='uploader')


class Lobby(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    description = db.Column(db.String(512), default='')
    password_hash = db.Column(db.String(256), nullable=True)  # NULL = public
    max_players = db.Column(db.Integer, default=4)
    game_type = db.Column(db.String(32), nullable=True)   # e.g. 'shadow_empire', 'civ4'
    is_locked = db.Column(db.Boolean, default=False, nullable=False)
    is_archived = db.Column(db.Boolean, default=False, nullable=False)
    current_player_idx = db.Column(db.Integer, default=0, nullable=False)
    current_round = db.Column(db.Integer, default=1, nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=_utcnow)

    owner = db.relationship('User')
    members = db.relationship('LobbyMember', back_populates='lobby', cascade='all, delete-orphan')
    savegames = db.relationship('SavegameFile', back_populates='lobby', cascade='all, delete-orphan')
    chat_messages = db.relationship('ChatMessage', cascade='all, delete-orphan')

    @property
    def has_started(self):
        """True once at least one savegame has been uploaded (game is underway)."""
        return len(self.savegames) > 0

    @property
    def is_password_protected(self):
        return self.password_hash is not None

    @property
    def player_count(self):
        return len(self.members)

    @property
    def ordered_members(self):
        return sorted(
            [m for m in self.members if m.play_order is not None],
            key=lambda m: m.play_order,
        )

    @property
    def current_member(self):
        ordered = self.ordered_members
        if not ordered or not self.is_locked:
            return None
        return ordered[self.current_player_idx % len(ordered)]


class LobbyMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lobby_id = db.Column(db.Integer, db.ForeignKey('lobby.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    joined_at = db.Column(db.DateTime, default=_utcnow)
    play_order = db.Column(db.Integer, nullable=True)  # NULL until game starts

    __table_args__ = (db.UniqueConstraint('lobby_id', 'user_id'),)

    lobby = db.relationship('Lobby', back_populates='members')
    user = db.relationship('User', back_populates='memberships')


class SavegameFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lobby_id = db.Column(db.Integer, db.ForeignKey('lobby.id'), nullable=False)
    uploader_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    original_name = db.Column(db.String(256), nullable=False)
    stored_name = db.Column(db.String(256), nullable=False)
    round_number = db.Column(db.Integer, default=1)
    note = db.Column(db.String(512), default='')
    uploaded_at = db.Column(db.DateTime, default=_utcnow)

    lobby = db.relationship('Lobby', back_populates='savegames')
    uploader = db.relationship('User', back_populates='uploads')


class PlayerNote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    lobby_id = db.Column(db.Integer, db.ForeignKey('lobby.id'), nullable=False)
    round_number = db.Column(db.Integer, nullable=True)  # NULL = general note
    content = db.Column(db.Text, nullable=False)
    updated_at = db.Column(db.DateTime, default=_utcnow)


class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lobby_id = db.Column(db.Integer, db.ForeignKey('lobby.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.String(1000), nullable=False)
    created_at = db.Column(db.DateTime, default=_utcnow)

    user = db.relationship('User')
