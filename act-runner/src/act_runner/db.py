import logging
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS builds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_url TEXT NOT NULL,
    repo_name TEXT NOT NULL,
    branch TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    started_at TEXT NOT NULL,
    finished_at TEXT,
    duration_ms INTEGER,
    log_path TEXT,
    exit_code INTEGER,
    error TEXT,
    UNIQUE(repo_url, branch, commit_sha)
)
"""


@dataclass
class Build:
    id: Optional[int] = None
    repo_url: str = ""
    repo_name: str = ""
    branch: str = ""
    commit_sha: str = ""
    status: str = "pending"
    started_at: str = ""
    finished_at: Optional[str] = None
    duration_ms: Optional[int] = None
    log_path: Optional[str] = None
    exit_code: Optional[int] = None
    error: Optional[str] = None


class BuildDB:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(CREATE_TABLE_SQL)
            conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def insert_build(self, build: Build) -> int:
        with self._get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO builds (repo_url, repo_name, branch, commit_sha, status,
                   started_at, finished_at, duration_ms, log_path, exit_code, error)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    build.repo_url,
                    build.repo_name,
                    build.branch,
                    build.commit_sha,
                    build.status,
                    build.started_at,
                    build.finished_at,
                    build.duration_ms,
                    build.log_path,
                    build.exit_code,
                    build.error,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def update_build(self, build_id: int, **kwargs):
        if not kwargs:
            return
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [build_id]
        with self._get_conn() as conn:
            conn.execute(f"UPDATE builds SET {sets} WHERE id = ?", values)
            conn.commit()

    def get_build(self, build_id: int) -> Optional[Build]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM builds WHERE id = ?", (build_id,)).fetchone()
            if not row:
                return None
            return Build(**dict(row))

    def list_builds(self, limit: int = 50, offset: int = 0) -> list[Build]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM builds ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [Build(**dict(r)) for r in rows]

    def get_last_build_for_repo(self, repo_url: str, branch: str) -> Optional[Build]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM builds WHERE repo_url = ? AND branch = ? ORDER BY id DESC LIMIT 1",
                (repo_url, branch),
            ).fetchone()
            if not row:
                return None
            return Build(**dict(row))

    def get_last_commit(self, repo_url: str, branch: str) -> Optional[str]:
        build = self.get_last_build_for_repo(repo_url, branch)
        return build.commit_sha if build else None
