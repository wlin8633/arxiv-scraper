from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import Paper


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self._initialize()

    def _initialize(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS papers (
                arxiv_id TEXT PRIMARY KEY,
                library_author_token TEXT NOT NULL,
                first_seen_year INTEGER NOT NULL,
                first_seen_at TEXT NOT NULL,
                latest_version INTEGER NOT NULL,
                title TEXT NOT NULL,
                authors_json TEXT NOT NULL,
                categories_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS versions (
                arxiv_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                published TEXT NOT NULL,
                updated TEXT NOT NULL,
                score REAL NOT NULL,
                matched_rules_json TEXT NOT NULL,
                suggested_filename TEXT NOT NULL,
                status TEXT NOT NULL,
                pdf_path TEXT,
                sha256 TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                PRIMARY KEY (arxiv_id, version),
                FOREIGN KEY (arxiv_id) REFERENCES papers(arxiv_id)
            );

            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                run_date TEXT NOT NULL,
                fetched_count INTEGER NOT NULL DEFAULT 0,
                indexed_count INTEGER NOT NULL DEFAULT 0,
                downloaded_count INTEGER NOT NULL DEFAULT 0,
                failed_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def begin_run(self, run_date: str) -> int:
        cursor = self.connection.execute(
            "INSERT INTO runs (started_at, run_date, status) VALUES (?, ?, ?)",
            (utc_now(), run_date, "running"),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def finish_run(
        self,
        run_id: int,
        fetched: int,
        indexed: int,
        downloaded: int,
        failed: int,
    ) -> None:
        status = "completed" if failed == 0 else "completed_with_errors"
        self.connection.execute(
            """
            UPDATE runs
            SET completed_at = ?, fetched_count = ?, indexed_count = ?,
                downloaded_count = ?, failed_count = ?, status = ?
            WHERE id = ?
            """,
            (utc_now(), fetched, indexed, downloaded, failed, status, run_id),
        )
        self.connection.commit()

    def fail_run(self, run_id: int) -> None:
        self.connection.execute(
            "UPDATE runs SET completed_at = ?, status = ? WHERE id = ?",
            (utc_now(), "failed", run_id),
        )
        self.connection.commit()

    def has_version(self, arxiv_id: str, version: int) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM versions WHERE arxiv_id = ? AND version = ?",
            (arxiv_id, version),
        ).fetchone()
        return row is not None

    def assign_identity(self, paper: Paper, proposed_token: str, proposed_year: int) -> tuple[str, int]:
        row = self.connection.execute(
            "SELECT library_author_token, first_seen_year FROM papers WHERE arxiv_id = ?",
            (paper.arxiv_id,),
        ).fetchone()
        if row:
            token, year = str(row["library_author_token"]), int(row["first_seen_year"])
            if token == "Unknown" and proposed_token != "Unknown":
                token = proposed_token
            self.connection.execute(
                """
                UPDATE papers
                SET library_author_token = ?, latest_version = MAX(latest_version, ?), title = ?,
                    authors_json = ?, categories_json = ?
                WHERE arxiv_id = ?
                """,
                (
                    token,
                    paper.version,
                    paper.title,
                    json.dumps(paper.authors, ensure_ascii=False),
                    json.dumps(paper.categories, ensure_ascii=False),
                    paper.arxiv_id,
                ),
            )
        else:
            token, year = proposed_token, proposed_year
            self.connection.execute(
                """
                INSERT INTO papers (
                    arxiv_id, library_author_token, first_seen_year, first_seen_at,
                    latest_version, title, authors_json, categories_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    paper.arxiv_id,
                    token,
                    year,
                    utc_now(),
                    paper.version,
                    paper.title,
                    json.dumps(paper.authors, ensure_ascii=False),
                    json.dumps(paper.categories, ensure_ascii=False),
                ),
            )
        self.connection.commit()
        return token, year

    def record_version(self, paper: Paper) -> None:
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO versions (
                arxiv_id, version, published, updated, score, matched_rules_json,
                suggested_filename, status, pdf_path, sha256, first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(arxiv_id, version) DO UPDATE SET
                updated = excluded.updated,
                score = excluded.score,
                matched_rules_json = excluded.matched_rules_json,
                suggested_filename = excluded.suggested_filename,
                status = excluded.status,
                pdf_path = excluded.pdf_path,
                sha256 = excluded.sha256,
                last_seen_at = excluded.last_seen_at
            """,
            (
                paper.arxiv_id,
                paper.version,
                paper.published,
                paper.updated,
                paper.score,
                json.dumps(paper.matched_rules, ensure_ascii=False),
                paper.suggested_filename,
                paper.status,
                paper.local_pdf,
                paper.sha256,
                now,
                now,
            ),
        )
        self.connection.commit()
