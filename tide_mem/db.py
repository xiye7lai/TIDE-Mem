from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .text import fts_query, utc_now_iso


class MemoryDB:
    """Small, auditable SQLite/FTS5 storage layer with hard user scoping."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=60.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=60000")
        return connection

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(self._initialize_sync)

    def _initialize_sync(self) -> None:
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS requests (
                    request_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    role TEXT,
                    content TEXT NOT NULL,
                    searchable_text TEXT NOT NULL,
                    timestamp_ms INTEGER,
                    event_time TEXT,
                    event_time_ms INTEGER,
                    ordering_ms INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    entities_json TEXT NOT NULL,
                    keywords_json TEXT NOT NULL,
                    state_key TEXT,
                    change_type TEXT NOT NULL,
                    is_current INTEGER NOT NULL DEFAULT 0,
                    source_indices_json TEXT NOT NULL,
                    FOREIGN KEY(request_id) REFERENCES requests(request_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_memories_user_order
                    ON memories(user_id, ordering_ms DESC);
                CREATE INDEX IF NOT EXISTS idx_memories_user_session
                    ON memories(user_id, session_id);
                CREATE INDEX IF NOT EXISTS idx_memories_user_state
                    ON memories(user_id, state_key, is_current, ordering_ms DESC);
                CREATE INDEX IF NOT EXISTS idx_memories_created
                    ON memories(created_at);

                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                    memory_id UNINDEXED,
                    user_id UNINDEXED,
                    searchable_text,
                    content,
                    tokenize='unicode61 remove_diacritics 2'
                );
                """
            )
            connection.commit()
        finally:
            connection.close()

    async def ping(self) -> bool:
        return await asyncio.to_thread(self._ping_sync)

    def _ping_sync(self) -> bool:
        connection = self._connect()
        try:
            row = connection.execute("SELECT 1 AS ok").fetchone()
            return bool(row and row["ok"] == 1)
        finally:
            connection.close()

    async def request_identity(self, request_id: str) -> tuple[str, str] | None:
        return await asyncio.to_thread(self._request_identity_sync, request_id)

    def _request_identity_sync(self, request_id: str) -> tuple[str, str] | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT user_id, session_id FROM requests WHERE request_id=? LIMIT 1",
                (request_id,),
            ).fetchone()
            if row is None:
                return None
            return str(row["user_id"]), str(row["session_id"])
        finally:
            connection.close()

    async def request_exists(self, request_id: str) -> bool:
        return await self.request_identity(request_id) is not None

    async def insert_bundle(
        self,
        *,
        request_id: str,
        user_id: str,
        session_id: str,
        records: list[dict[str, Any]],
    ) -> bool:
        """Atomically inserts a request and all records; False means idempotent replay."""
        return await asyncio.to_thread(
            self._insert_bundle_sync,
            request_id,
            user_id,
            session_id,
            records,
        )

    def _insert_bundle_sync(
        self,
        request_id: str,
        user_id: str,
        session_id: str,
        records: list[dict[str, Any]],
    ) -> bool:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            inserted = connection.execute(
                """
                INSERT OR IGNORE INTO requests(request_id, user_id, session_id, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (request_id, user_id, session_id, utc_now_iso()),
            ).rowcount
            if inserted == 0:
                connection.rollback()
                return False

            state_keys: set[str] = set()
            for record in records:
                connection.execute(
                    """
                    INSERT INTO memories(
                        id, request_id, user_id, session_id, kind, role, content,
                        searchable_text, timestamp_ms, event_time, event_time_ms,
                        ordering_ms, created_at, entities_json, keywords_json,
                        state_key, change_type, is_current, source_indices_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["id"],
                        request_id,
                        user_id,
                        session_id,
                        record["kind"],
                        record.get("role"),
                        record["content"],
                        record["searchable_text"],
                        record.get("timestamp_ms"),
                        record.get("event_time"),
                        record.get("event_time_ms"),
                        record["ordering_ms"],
                        record["created_at"],
                        record["entities_json"],
                        record["keywords_json"],
                        record.get("state_key"),
                        record.get("change_type", "none"),
                        int(bool(record.get("is_current", False))),
                        record["source_indices_json"],
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO memories_fts(memory_id, user_id, searchable_text, content)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        record["id"],
                        user_id,
                        record["searchable_text"],
                        record["content"],
                    ),
                )
                if record.get("state_key") and record.get("change_type") in {
                    "set",
                    "cancel",
                    "complete",
                }:
                    state_keys.add(record["state_key"])

            # Recompute the current member from event/source time, so concurrent or
            # out-of-order Add calls do not silently make arrival order the truth.
            for state_key in state_keys:
                connection.execute(
                    """
                    UPDATE memories SET is_current=0
                    WHERE user_id=? AND state_key=?
                      AND change_type IN ('set', 'cancel', 'complete')
                    """,
                    (user_id, state_key),
                )
                newest = connection.execute(
                    """
                    SELECT id FROM memories
                    WHERE user_id=? AND state_key=?
                      AND change_type IN ('set', 'cancel', 'complete')
                    ORDER BY ordering_ms DESC, created_at DESC, id DESC
                    LIMIT 1
                    """,
                    (user_id, state_key),
                ).fetchone()
                if newest:
                    connection.execute(
                        "UPDATE memories SET is_current=1 WHERE id=?", (newest["id"],)
                    )

            connection.commit()
            return True
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    async def fts_search(self, user_id: str, query: str, limit: int) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._fts_search_sync, user_id, query, limit)

    def _fts_search_sync(self, user_id: str, query: str, limit: int) -> list[dict[str, Any]]:
        expression = fts_query(query)
        if not expression:
            return []
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT m.*, bm25(memories_fts, 0.0, 0.0, 1.0, 0.35) AS lexical_rank
                FROM memories_fts
                JOIN memories AS m ON m.id = memories_fts.memory_id
                WHERE memories_fts MATCH ? AND memories_fts.user_id = ?
                ORDER BY lexical_rank ASC, m.ordering_ms DESC
                LIMIT ?
                """,
                (expression, user_id, limit),
            ).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.OperationalError:
            # A safe query builder is used, but malformed Unicode/tokenizer edge
            # cases should degrade to the exact/LIKE channel rather than fail Search.
            return []
        finally:
            connection.close()

    async def exact_search(
        self,
        user_id: str,
        terms: Iterable[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        clean = [term.strip().casefold() for term in terms if term and term.strip()]
        return await asyncio.to_thread(self._exact_search_sync, user_id, clean[:20], limit)

    def _exact_search_sync(
        self,
        user_id: str,
        terms: list[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        if not terms:
            return []
        clauses = ["lower(searchable_text) LIKE ?" for _ in terms]
        params: list[Any] = [user_id]
        params.extend(f"%{term}%" for term in terms)
        params.append(limit)
        query = f"""
            SELECT * FROM memories
            WHERE user_id=? AND ({' OR '.join(clauses)})
            ORDER BY is_current DESC, ordering_ms DESC
            LIMIT ?
        """
        connection = self._connect()
        try:
            return [dict(row) for row in connection.execute(query, params).fetchall()]
        finally:
            connection.close()

    async def current_states(self, user_id: str, limit: int = 48) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._current_states_sync, user_id, limit)

    def _current_states_sync(self, user_id: str, limit: int) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT state_key, content, event_time, ordering_ms
                FROM memories
                WHERE user_id=? AND is_current=1 AND state_key IS NOT NULL
                ORDER BY ordering_ms DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    async def recent_memories(self, user_id: str, limit: int) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._recent_memories_sync, user_id, limit)

    def _recent_memories_sync(self, user_id: str, limit: int) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT * FROM memories
                WHERE user_id=?
                ORDER BY is_current DESC, ordering_ms DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    async def fetch_by_ids(self, user_id: str, ids: list[str]) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._fetch_by_ids_sync, user_id, ids)

    def _fetch_by_ids_sync(self, user_id: str, ids: list[str]) -> list[dict[str, Any]]:
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        connection = self._connect()
        try:
            rows = connection.execute(
                f"SELECT * FROM memories WHERE user_id=? AND id IN ({placeholders})",
                [user_id, *ids],
            ).fetchall()
            by_id = {row["id"]: dict(row) for row in rows}
            return [by_id[ident] for ident in ids if ident in by_id]
        finally:
            connection.close()

    async def purge_older_than(self, days: int) -> int:
        return await asyncio.to_thread(self._purge_older_than_sync, days)

    def _purge_older_than_sync(self, days: int) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat().replace("+00:00", "Z")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            ids = [
                row["id"]
                for row in connection.execute(
                    "SELECT id FROM memories WHERE created_at < ?", (cutoff,)
                ).fetchall()
            ]
            if ids:
                for start in range(0, len(ids), 500):
                    chunk = ids[start : start + 500]
                    placeholders = ",".join("?" for _ in chunk)
                    connection.execute(
                        f"DELETE FROM memories_fts WHERE memory_id IN ({placeholders})", chunk
                    )
                    connection.execute(
                        f"DELETE FROM memories WHERE id IN ({placeholders})", chunk
                    )
            connection.execute(
                """
                DELETE FROM requests
                WHERE created_at < ?
                  AND NOT EXISTS (
                    SELECT 1 FROM memories WHERE memories.request_id=requests.request_id
                  )
                """,
                (cutoff,),
            )
            connection.commit()
            return len(ids)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    async def count_memories(self, user_id: str | None = None) -> int:
        return await asyncio.to_thread(self._count_memories_sync, user_id)

    def _count_memories_sync(self, user_id: str | None) -> int:
        connection = self._connect()
        try:
            if user_id is None:
                row = connection.execute("SELECT COUNT(*) AS n FROM memories").fetchone()
            else:
                row = connection.execute(
                    "SELECT COUNT(*) AS n FROM memories WHERE user_id=?", (user_id,)
                ).fetchone()
            return int(row["n"] if row else 0)
        finally:
            connection.close()
