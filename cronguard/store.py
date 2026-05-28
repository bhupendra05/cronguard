"""SQLite-backed store for job heartbeats and definitions."""
from __future__ import annotations
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional


@dataclass
class JobDef:
    name: str
    schedule: str       # cron expression
    grace_seconds: int  # how many seconds late before flagged as missed
    enabled: bool = True


@dataclass
class Heartbeat:
    name: str
    last_seen: datetime   # UTC


class CronStore:
    """Persist job definitions and heartbeats in SQLite."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                name          TEXT PRIMARY KEY,
                schedule      TEXT NOT NULL,
                grace_seconds INTEGER NOT NULL DEFAULT 60,
                enabled       INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS heartbeats (
                name      TEXT PRIMARY KEY,
                last_seen TEXT NOT NULL
            );
        """)
        self._conn.commit()

    # ------------------------------------------------------------------ #
    # Job definitions
    # ------------------------------------------------------------------ #

    def register(self, job: JobDef) -> None:
        self._conn.execute(
            """
            INSERT INTO jobs (name, schedule, grace_seconds, enabled)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                schedule=excluded.schedule,
                grace_seconds=excluded.grace_seconds,
                enabled=excluded.enabled
            """,
            (job.name, job.schedule, job.grace_seconds, int(job.enabled)),
        )
        self._conn.commit()

    def unregister(self, name: str) -> bool:
        cur = self._conn.execute("DELETE FROM jobs WHERE name = ?", (name,))
        self._conn.commit()
        return cur.rowcount > 0

    def get_job(self, name: str) -> Optional[JobDef]:
        row = self._conn.execute("SELECT * FROM jobs WHERE name = ?", (name,)).fetchone()
        if row is None:
            return None
        return JobDef(
            name=row["name"],
            schedule=row["schedule"],
            grace_seconds=row["grace_seconds"],
            enabled=bool(row["enabled"]),
        )

    def list_jobs(self) -> List[JobDef]:
        rows = self._conn.execute("SELECT * FROM jobs ORDER BY name").fetchall()
        return [
            JobDef(name=r["name"], schedule=r["schedule"],
                   grace_seconds=r["grace_seconds"], enabled=bool(r["enabled"]))
            for r in rows
        ]

    # ------------------------------------------------------------------ #
    # Heartbeats
    # ------------------------------------------------------------------ #

    def heartbeat(self, name: str, at: Optional[datetime] = None) -> None:
        ts = (at or datetime.now(timezone.utc)).isoformat()
        self._conn.execute(
            """
            INSERT INTO heartbeats (name, last_seen) VALUES (?, ?)
            ON CONFLICT(name) DO UPDATE SET last_seen=excluded.last_seen
            """,
            (name, ts),
        )
        self._conn.commit()

    def get_heartbeat(self, name: str) -> Optional[Heartbeat]:
        row = self._conn.execute("SELECT * FROM heartbeats WHERE name = ?", (name,)).fetchone()
        if row is None:
            return None
        return Heartbeat(name=row["name"], last_seen=datetime.fromisoformat(row["last_seen"]))

    def list_heartbeats(self) -> List[Heartbeat]:
        rows = self._conn.execute("SELECT * FROM heartbeats ORDER BY name").fetchall()
        return [Heartbeat(name=r["name"], last_seen=datetime.fromisoformat(r["last_seen"]))
                for r in rows]

    def close(self) -> None:
        self._conn.close()

    @classmethod
    def open(cls, path: str) -> "CronStore":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        return cls(path)
