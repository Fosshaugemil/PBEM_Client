"""Savegame format validators.

Each validator receives a werkzeug FileStorage object and returns (ok, error_message).
The file stream is rewound to position 0 before returning so the caller can still save it.
"""

_ZIP_MAGIC = b'PK\x03\x04'


def _validate_shadow_empire(file_storage):
    name = file_storage.filename or ''
    if not name.lower().endswith('.se1'):
        return False, 'Shadow Empire saves must have a .se1 extension.'
    header = file_storage.stream.read(4)
    file_storage.stream.seek(0)
    if header != _ZIP_MAGIC:
        return False, 'File does not appear to be a valid Shadow Empire save (invalid file header).'
    return True, None


GAME_VALIDATORS = {
    'shadow_empire': _validate_shadow_empire,
}

GAME_TYPE_LABELS = {
    'shadow_empire': 'Shadow Empire',
}


def validate_savegame(file_storage, game_type):
    """Validate a savegame file against the expected format for the given game type.

    Returns (ok: bool, error: str | None).
    """
    validator = GAME_VALIDATORS.get(game_type)
    if validator is None:
        return False, f'Unknown game type: {game_type}'
    return validator(file_storage)
