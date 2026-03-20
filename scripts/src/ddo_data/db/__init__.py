"""DDO game database — context-managed SQLite wrapper."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .schema import create_schema
from .writers import insert_augments, insert_enhancement_trees, insert_feats, insert_items, insert_set_bonus_effects, insert_spells

__all__ = ["GameDB"]


class GameDB:
    """Context-managed wrapper around the DDO SQLite game database.

    Usage::

        with GameDB(Path("public/data/ddo.db")) as db:
            db.create_schema()
            db.insert_items(items)
            db.insert_feats(feats)

    Pass ``":memory:"`` as *path* for in-memory databases (useful in tests).
    """

    def __init__(self, path: Path | str) -> None:
        self._path = str(path)
        self._conn: sqlite3.Connection | None = None

    def __enter__(self) -> "GameDB":
        self._conn = sqlite3.connect(self._path)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        if self._conn is not None:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        """The underlying sqlite3 connection (only valid inside ``with`` block)."""
        if self._conn is None:
            raise RuntimeError("GameDB must be used as a context manager (with GameDB(...) as db)")
        return self._conn

    def create_schema(self) -> None:
        """Apply DDL and seed reference data.  Safe to call on an existing DB."""
        create_schema(self.conn)

    def insert_items(self, items: list[dict]) -> int:
        """Insert item dicts (from wiki/game_data parsers).  Returns row count."""
        return insert_items(self.conn, items)

    def insert_feats(self, feats: list[dict]) -> int:
        """Insert feat dicts (from wiki parsers).  Returns row count."""
        return insert_feats(self.conn, feats)

    def insert_enhancement_trees(self, trees: list[dict]) -> int:
        """Insert enhancement tree dicts (from wiki scraper).  Returns row count."""
        return insert_enhancement_trees(self.conn, trees)

    def insert_set_bonus_effects(self, sets: list[dict]) -> int:
        """Insert set bonus effects (from wiki scraper).  Returns row count."""
        return insert_set_bonus_effects(self.conn, sets)

    def insert_augments(self, augments: list[dict]) -> int:
        """Insert augment dicts (from wiki scraper).  Returns row count."""
        return insert_augments(self.conn, augments)

    def insert_spells(self, spells: list[dict]) -> int:
        """Insert spell dicts (from wiki scraper).  Returns row count."""
        return insert_spells(self.conn, spells)
