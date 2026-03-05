import os
import secrets
import warnings

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Railway (and many PaaS) inject DATABASE_URL as "postgres://..." but
# SQLAlchemy ≥ 1.4 requires "postgresql://".
_db_url = os.environ.get(
    'DATABASE_URL',
    f'sqlite:///{os.path.join(BASE_DIR, "instance", "pbem.db")}',
)
if _db_url.startswith('postgres://'):
    _db_url = _db_url.replace('postgres://', 'postgresql://', 1)

_secret_key = os.environ.get('SECRET_KEY')
if _secret_key is None:
    _secret_key = secrets.token_hex(32)
    warnings.warn(
        "SECRET_KEY is not set — a random key was generated. "
        "All sessions will be invalidated on every restart. "
        "Set the SECRET_KEY environment variable in production.",
        stacklevel=2,
    )


class Config:
    SECRET_KEY = _secret_key
    SQLALCHEMY_DATABASE_URI = _db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', os.path.join(BASE_DIR, 'uploads'))
    MAX_CONTENT_LENGTH = 64 * 1024 * 1024  # 64 MB
