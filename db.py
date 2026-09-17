"""SQLite storage for watched X/Twitter handles.

Two tables:
- watches: which chat is watching which handle
- handle_state: the last tweet id seen for a handle (shared across all
  chats watching it, so we only hit the API once per handle per cycle)
"""

import sqlite3
import threading
from typing import Optional


class Database:
    def __init__(self, path: str):
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS watches (
                    chat_id INTEGER NOT NULL,
                    handle TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (chat_id, handle)
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS handle_state (
                    handle TEXT PRIMARY KEY,
                    last_tweet_id TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    # -- watches -----------------------------------------------------

    def add_watch(self, chat_id: int, handle: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO watches (chat_id, handle) VALUES (?, ?)",
                (chat_id, handle),
            )

    def remove_watch(self, chat_id: int, handle: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "DELETE FROM watches WHERE chat_id = ? AND handle = ?",
                (chat_id, handle),
            )
            return cur.rowcount > 0

    def is_watching(self, chat_id: int, handle: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "SELECT 1 FROM watches WHERE chat_id = ? AND handle = ?",
                (chat_id, handle),
            )
            return cur.fetchone() is not None

    def list_watches(self, chat_id: int) -> list[str]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT handle FROM watches WHERE chat_id = ? ORDER BY handle",
                (chat_id,),
            )
            return [row["handle"] for row in cur.fetchall()]

    def list_active_handles(self) -> list[str]:
        with self._lock:
            cur = self._conn.execute("SELECT DISTINCT handle FROM watches")
            return [row["handle"] for row in cur.fetchall()]

    def list_chats_for_handle(self, handle: str) -> list[int]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT chat_id FROM watches WHERE handle = ?", (handle,)
            )
            return [row["chat_id"] for row in cur.fetchall()]

    # -- handle state --------------------------------------------------

    def get_handle_state(self, handle: str) -> Optional[sqlite3.Row]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM handle_state WHERE handle = ?", (handle,)
            )
            return cur.fetchone()

    def set_handle_state(self, handle: str, last_tweet_id: Optional[str]) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO handle_state (handle, last_tweet_id, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(handle) DO UPDATE SET
                    last_tweet_id = excluded.last_tweet_id,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (handle, last_tweet_id),
            )
