"""
Which backing store the app reads game data from.

One switch, three values, read fresh on every call so it can be changed
without a redeploy:

    GAME_SOURCE=db_only          database only; never touch DATA_ROOT_DIR
    GAME_SOURCE=data_root_only   JSON files under DATA_ROOT_DIR only; never
                                 open a database connection
    GAME_SOURCE=combined         database first, filesystem as fallback
                                 (the default, and the historical behaviour)

On Azure this is an App Setting, so changing it bounces the workers. Locally
it is a line in .env, or exported in the shell.

Consumers ask the two predicates rather than the mode string: ``use_db()``
and ``use_files()``. Both are true only in ``combined``, which is what makes
the fallback chain a mode rather than a special case scattered through the
call sites.
"""
from __future__ import annotations

import os

DB_ONLY = "db_only"
DATA_ROOT_ONLY = "data_root_only"
COMBINED = "combined"

MODES = (DB_ONLY, DATA_ROOT_ONLY, COMBINED)
DEFAULT_MODE = COMBINED


def game_source() -> str:
    """The active mode. Unset or unrecognised values fall back to COMBINED."""
    mode = os.getenv("GAME_SOURCE", "").strip().lower()
    return mode if mode in MODES else DEFAULT_MODE


def use_db() -> bool:
    return game_source() != DATA_ROOT_ONLY


def use_files() -> bool:
    return game_source() != DB_ONLY
