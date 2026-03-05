"""
Savegame file validators for supported PBEM game types.

Each validator receives (file_obj, original_filename, file_size_bytes) and
returns (ok: bool, error_message: str).  An empty error string means success.

Adding a new game:
  1. Write a validate_<game>() function below.
  2. Add it to GAME_VALIDATORS with a short key string.
  3. Add a display name to GAME_DISPLAY_NAMES.
"""

import os


# ---------------------------------------------------------------------------
# Magic-byte / header helpers
# ---------------------------------------------------------------------------

# File headers that are never valid game saves.
_BAD_MAGIC = [
    (b'MZ',         'Windows PE executable'),
    (b'\x7fELF',    'Linux ELF executable'),
    (b'\xca\xfe\xba\xbe', 'Mach-O executable'),
    (b'%PDF',       'PDF document'),
    (b'\xff\xfe',   'UTF-16 LE text'),
    (b'\xfe\xff',   'UTF-16 BE text'),
    (b'\xef\xbb\xbf','UTF-8 BOM text'),
    (b'<!DO',       'HTML document'),
    (b'<htm',       'HTML document'),
    (b'<HTM',       'HTML document'),
    (b'<?ph',       'PHP script'),
    (b'<?xm',       'XML document'),
    (b'#!/',        'shell script'),
    (b'#!/',        'shell script'),
    (b'\x89PNG',    'PNG image'),
    (b'\xff\xd8\xff','JPEG image'),
    (b'GIF8',       'GIF image'),
    (b'RIFF',       'RIFF/WAV/AVI media'),
    (b'fLaC',       'FLAC audio'),
    (b'ID3',        'MP3 audio'),
    (b'OggS',       'Ogg media'),
]


def _read_header(f, n=32):
    """Read first *n* bytes from *f* and seek back to the start."""
    header = f.read(n)
    f.seek(0)
    return header


def _check_not_dangerous(header):
    """Return an error string if *header* matches a known-bad signature."""
    for magic, label in _BAD_MAGIC:
        if header[:len(magic)] == magic:
            return f'File looks like a {label}, not a game save.'
    return None


def _ext(filename):
    return os.path.splitext(filename)[1].lower()


# ---------------------------------------------------------------------------
# Shadow Empire
# ---------------------------------------------------------------------------
# Shadow Empire stores saves as binary .sav files (proprietary format).
# Real saves are several MB for active games.  We validate:
#   • Extension is .sav
#   • File is at least 4 KB
#   • Header does not match any known-dangerous format
#   • First 4 bytes are not all-zero (empty/corrupt file guard)

_SE_MIN_SIZE = 4 * 1024       # 4 KB
_SE_ALLOWED_EXTS = {'.se1'}


def validate_shadow_empire(f, filename, size):
    if _ext(filename) not in _SE_ALLOWED_EXTS:
        return False, (
            f'Shadow Empire saves must use the .se1 extension '
            f'(uploaded file has {_ext(filename)!r}).'
        )
    if size < _SE_MIN_SIZE:
        return False, (
            f'File is too small to be a valid Shadow Empire save '
            f'({size} bytes; expected at least {_SE_MIN_SIZE} bytes).'
        )
    header = _read_header(f, 32)
    err = _check_not_dangerous(header)
    if err:
        return False, err
    if header[:4] == b'\x00\x00\x00\x00':
        return False, 'File appears to be empty or corrupt (null header).'
    return True, ''


# ---------------------------------------------------------------------------
# Civilization IV (Beyond the Sword / Warlords / vanilla)
# ---------------------------------------------------------------------------
# Civ4 saves use the .CivBeyondSwordSave (or .CivWarlordsSave / .Civ4Save)
# binary format.  The header starts with a 4-byte little-endian integer
# (chunk tag) followed by binary data; real saves are typically 50 KB–5 MB.

_CIV4_MIN_SIZE = 10 * 1024    # 10 KB
_CIV4_ALLOWED_EXTS = {
    '.civbeyondswordsave',
    '.civwarlordssave',
    '.civ4save',
    '.civ4',
}


def validate_civ4(f, filename, size):
    if _ext(filename) not in _CIV4_ALLOWED_EXTS:
        return False, (
            f'Civ4 saves must use a recognised extension '
            f'(.CivBeyondSwordSave, .CivWarlordsSave, .Civ4Save). '
            f'Got {_ext(filename)!r}.'
        )
    if size < _CIV4_MIN_SIZE:
        return False, (
            f'File is too small to be a valid Civ4 save '
            f'({size} bytes; expected at least {_CIV4_MIN_SIZE} bytes).'
        )
    header = _read_header(f, 32)
    err = _check_not_dangerous(header)
    if err:
        return False, err
    # Civ4 saves must start with non-zero binary data (4-byte chunk tag)
    if header[:4] == b'\x00\x00\x00\x00':
        return False, 'File appears to be empty or corrupt (null header).'
    return True, ''


# ---------------------------------------------------------------------------
# Civilization V
# ---------------------------------------------------------------------------
# Civ5 saves use the .Civ5Save format (binary, typically 1–20 MB).
# The file starts with the ASCII magic "CIV5" (4 bytes).

_CIV5_MAGIC = b'CIV5'
_CIV5_MIN_SIZE = 50 * 1024    # 50 KB
_CIV5_ALLOWED_EXTS = {'.civ5save', '.civ5'}


def validate_civ5(f, filename, size):
    if _ext(filename) not in _CIV5_ALLOWED_EXTS:
        return False, (
            f'Civ5 saves must use the .Civ5Save extension '
            f'(got {_ext(filename)!r}).'
        )
    if size < _CIV5_MIN_SIZE:
        return False, (
            f'File is too small to be a valid Civ5 save '
            f'({size} bytes; expected at least {_CIV5_MIN_SIZE} bytes).'
        )
    header = _read_header(f, 8)
    if header[:4] != _CIV5_MAGIC:
        return False, (
            f'File does not have the Civ5 save signature '
            f'(expected {_CIV5_MAGIC!r} at offset 0).'
        )
    return True, ''


# ---------------------------------------------------------------------------
# Civilization VI
# ---------------------------------------------------------------------------
# Civ6 saves use the .Civ6Save format.  They start with "CIV6" (4 bytes).

_CIV6_MAGIC = b'CIV6'
_CIV6_MIN_SIZE = 100 * 1024   # 100 KB
_CIV6_ALLOWED_EXTS = {'.civ6save', '.civ6'}


def validate_civ6(f, filename, size):
    if _ext(filename) not in _CIV6_ALLOWED_EXTS:
        return False, (
            f'Civ6 saves must use the .Civ6Save extension '
            f'(got {_ext(filename)!r}).'
        )
    if size < _CIV6_MIN_SIZE:
        return False, (
            f'File is too small to be a valid Civ6 save '
            f'({size} bytes; expected at least {_CIV6_MIN_SIZE} bytes).'
        )
    header = _read_header(f, 8)
    if header[:4] != _CIV6_MAGIC:
        return False, (
            f'File does not have the Civ6 save signature '
            f'(expected {_CIV6_MAGIC!r} at offset 0).'
        )
    return True, ''


# ---------------------------------------------------------------------------
# Generic / Other PBEM game
# ---------------------------------------------------------------------------
# No game-specific checks — just reject obviously wrong file types and
# ensure the file is not empty.

_GENERIC_MIN_SIZE = 1  # any non-empty file is accepted


def validate_generic(f, filename, size):
    if size < _GENERIC_MIN_SIZE:
        return False, 'File is empty.'
    header = _read_header(f, 32)
    err = _check_not_dangerous(header)
    if err:
        return False, err
    return True, ''


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

#: Map game-type key → validator function.
GAME_VALIDATORS = {
    'shadow_empire': validate_shadow_empire,
    'civ4':          validate_civ4,
    'civ5':          validate_civ5,
    'civ6':          validate_civ6,
    'generic':       validate_generic,
}

#: Human-readable display names for each game type.
GAME_DISPLAY_NAMES = {
    'shadow_empire': 'Shadow Empire',
    'civ4':          'Civilization IV',
    'civ5':          'Civilization V',
    'civ6':          'Civilization VI',
    'generic':       'Generic / Other',
}
