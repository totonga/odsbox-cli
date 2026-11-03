"""Bounded command history, stored transactionally without recording private input."""

from __future__ import annotations

import sqlite3
import warnings
from collections.abc import Iterable
from pathlib import Path

from prompt_toolkit.history import History

LIMIT = 1000


class CommandHistory(History):
    def __init__(self, path: Path | None = None, *, enabled: bool = True) -> None:
        super().__init__()
        self.path = (path or Path.home() / ".odsbox-cli" / "history.sqlite3") if enabled else None
        self._entries: list[str] = []
        self._failed = False

    def _connect(self) -> sqlite3.Connection:
        assert self.path is not None
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        # Exclusive creation avoids changing permissions of an existing user file.
        try:
            with self.path.open("xb"):
                self.path.chmod(0o600)
        except FileExistsError:
            pass
        connection = sqlite3.connect(self.path, timeout=0.25)
        try:
            connection.execute("CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY, text TEXT NOT NULL)")
        except sqlite3.Error:
            connection.close()
            raise
        return connection

    def _warn(self, exc: OSError | sqlite3.Error) -> None:
        self._failed = True
        warnings.warn(
            f"Persistent history unavailable ({type(exc).__name__}); using memory only for this process.",
            stacklevel=3,
        )

    def refresh(self) -> None:
        """Reload between prompts, never on a keystroke or in disabled mode."""
        if self.path is not None and not self._failed:
            try:
                connection = self._connect()
                try:
                    self._entries = [
                        row[0]
                        for row in connection.execute(
                            "SELECT text FROM (SELECT id, text FROM history ORDER BY id DESC LIMIT ?) ORDER BY id",
                            (LIMIT,),
                        )
                    ]
                finally:
                    connection.close()
            except (OSError, sqlite3.Error) as exc:
                self._warn(exc)
        self._loaded_strings = list(reversed(self._entries))
        self._loaded = True

    def append_string(self, string: str) -> None:
        if not string.strip() or string.startswith(" "):
            return
        self.store_string(string)
        self._loaded_strings = list(reversed(self._entries))
        self._loaded = True

    def load_history_strings(self) -> Iterable[str]:
        self.refresh()
        return reversed(self._entries)

    def store_string(self, string: str) -> None:
        if not string.strip() or string.startswith(" "):
            return
        if self.path is not None and not self._failed:
            try:
                connection = self._connect()
                try:
                    with connection:
                        connection.execute("BEGIN IMMEDIATE")
                        last = connection.execute("SELECT text FROM history ORDER BY id DESC LIMIT 1").fetchone()
                        if last is None or last[0] != string:
                            connection.execute("INSERT INTO history(text) VALUES (?)", (string,))
                        connection.execute(
                            "DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY id DESC LIMIT ?)",
                            (LIMIT,),
                        )
                finally:
                    connection.close()
                self.refresh()
                return
            except (OSError, sqlite3.Error) as exc:
                self._warn(exc)
        if not self._entries or self._entries[-1] != string:
            self._entries.append(string)
            self._entries = self._entries[-LIMIT:]
