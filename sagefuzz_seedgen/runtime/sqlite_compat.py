from __future__ import annotations

import sys
from typing import Tuple


_MIN_RETURNING_SQLITE = (3, 35, 0)


def _parse_version(raw: str) -> Tuple[int, int, int]:
    parts = []
    for token in raw.split('.')[:3]:
        try:
            parts.append(int(token))
        except Exception:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def install_sqlite_compat() -> str:
    """Ensure sqlite3 has a new enough engine for SQL RETURNING support.

    Agno's SqliteDb path uses INSERT .. RETURNING. Ubuntu 20.04 ships sqlite 3.31,
    which cannot parse RETURNING. If needed and available, swap in pysqlite3-binary
    before SQLAlchemy/Agno import sqlite3.
    """
    import sqlite3 as stdlib_sqlite3

    if _parse_version(stdlib_sqlite3.sqlite_version) >= _MIN_RETURNING_SQLITE:
        return stdlib_sqlite3.sqlite_version

    try:
        import pysqlite3 as replacement_sqlite3  # type: ignore
    except Exception:
        return stdlib_sqlite3.sqlite_version

    replacement_version = getattr(replacement_sqlite3, 'sqlite_version', '')
    if _parse_version(replacement_version) < _MIN_RETURNING_SQLITE:
        return stdlib_sqlite3.sqlite_version

    sys.modules['sqlite3'] = replacement_sqlite3
    return replacement_version
