"""
SQLite email store with FTS5 full-text search.

Schema:
  emails          – one row per (folder, uid)
  attachments     – metadata (+ optional binary data)
  sync_state      – tracks last synced UID per folder
  emails_fts      – FTS5 virtual table over emails
"""

import base64
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

_store: Optional["EmailStore"] = None
_init_lock = threading.Lock()


def get_email_store() -> Optional["EmailStore"]:
    """Return the global EmailStore instance, or None if not initialised."""
    return _store


def init_email_store(db_path: str) -> "EmailStore":
    """Initialise (or return existing) global EmailStore."""
    global _store
    with _init_lock:
        if _store is None:
            _store = EmailStore(db_path)
    return _store


class EmailStore:
    """Thread-safe SQLite store for emails with FTS5 search."""

    _SCHEMA = """
        CREATE TABLE IF NOT EXISTS emails (
            id               INTEGER PRIMARY KEY,
            folder           TEXT    NOT NULL,
            uid              INTEGER NOT NULL,
            message_id       TEXT,
            subject          TEXT,
            from_addr        TEXT,
            to_addr          TEXT,
            cc_addr          TEXT,
            date_str         TEXT,
            body_text        TEXT,
            body_html        TEXT,
            has_attachments  INTEGER DEFAULT 0,
            is_read          INTEGER DEFAULT 0,
            is_flagged       INTEGER DEFAULT 0,
            synced_at        TEXT,
            UNIQUE(folder, uid)
        );

        CREATE TABLE IF NOT EXISTS attachments (
            id           INTEGER PRIMARY KEY,
            email_id     INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
            filename     TEXT,
            content_type TEXT,
            size         INTEGER,
            data         BLOB
        );

        CREATE TABLE IF NOT EXISTS sync_state (
            folder     TEXT PRIMARY KEY,
            last_uid   INTEGER DEFAULT 0,
            synced_at  TEXT
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS emails_fts USING fts5(
            subject, from_addr, to_addr, cc_addr, body_text,
            content=emails, content_rowid=id
        );

        -- Keep FTS in sync with emails table
        CREATE TRIGGER IF NOT EXISTS emails_ai AFTER INSERT ON emails BEGIN
            INSERT INTO emails_fts(rowid, subject, from_addr, to_addr, cc_addr, body_text)
            VALUES (new.id, new.subject, new.from_addr, new.to_addr, new.cc_addr, new.body_text);
        END;

        CREATE TRIGGER IF NOT EXISTS emails_ad AFTER DELETE ON emails BEGIN
            INSERT INTO emails_fts(emails_fts, rowid, subject, from_addr, to_addr, cc_addr, body_text)
            VALUES ('delete', old.id, old.subject, old.from_addr, old.to_addr, old.cc_addr, old.body_text);
        END;

        CREATE TRIGGER IF NOT EXISTS emails_au AFTER UPDATE ON emails BEGIN
            INSERT INTO emails_fts(emails_fts, rowid, subject, from_addr, to_addr, cc_addr, body_text)
            VALUES ('delete', old.id, old.subject, old.from_addr, old.to_addr, old.cc_addr, old.body_text);
            INSERT INTO emails_fts(rowid, subject, from_addr, to_addr, cc_addr, body_text)
            VALUES (new.id, new.subject, new.from_addr, new.to_addr, new.cc_addr, new.body_text);
        END;
    """

    def __init__(self, db_path: str) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._path = db_path
        self._local = threading.local()
        self._init_db()
        logging.info("EmailStore initialised at %s", db_path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        """Return a thread-local SQLite connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self._path, check_same_thread=False, timeout=30)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return self._local.conn

    def _init_db(self) -> None:
        conn = self._conn()
        conn.executescript(self._SCHEMA)
        conn.commit()

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def upsert_email(
        self,
        folder: str,
        uid: int,
        message_id: str | None,
        subject: str | None,
        from_addr: str | None,
        to_addr: str | None,
        cc_addr: str | None,
        date_str: str | None,
        body_text: str | None,
        body_html: str | None,
        is_read: bool = False,
        is_flagged: bool = False,
        attachments: list[dict] | None = None,
    ) -> int:
        """Insert or update an email. Returns the email row id."""
        conn = self._conn()
        now = datetime.utcnow().isoformat()
        has_attachments = 1 if attachments else 0

        cursor = conn.execute(
            """
            INSERT INTO emails
                (folder, uid, message_id, subject, from_addr, to_addr, cc_addr,
                 date_str, body_text, body_html, has_attachments, is_read, is_flagged, synced_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(folder, uid) DO UPDATE SET
                subject          = excluded.subject,
                from_addr        = excluded.from_addr,
                to_addr          = excluded.to_addr,
                cc_addr          = excluded.cc_addr,
                date_str         = excluded.date_str,
                body_text        = excluded.body_text,
                body_html        = excluded.body_html,
                has_attachments  = excluded.has_attachments,
                is_read          = excluded.is_read,
                is_flagged       = excluded.is_flagged,
                synced_at        = excluded.synced_at
            """,
            (
                folder,
                uid,
                message_id,
                subject,
                from_addr,
                to_addr,
                cc_addr,
                date_str,
                body_text,
                body_html,
                has_attachments,
                int(is_read),
                int(is_flagged),
                now,
            ),
        )
        email_id: int = cursor.lastrowid or 0

        # On UPDATE lastrowid may be 0 – fetch real id
        if email_id == 0:
            row = conn.execute(
                "SELECT id FROM emails WHERE folder=? AND uid=?", (folder, uid)
            ).fetchone()
            email_id = row["id"] if row else 0

        # Attachments: replace on upsert
        if attachments and email_id:
            conn.execute("DELETE FROM attachments WHERE email_id=?", (email_id,))
            for att in attachments:
                conn.execute(
                    "INSERT INTO attachments (email_id, filename, content_type, size, data) "
                    "VALUES (?,?,?,?,?)",
                    (
                        email_id,
                        att.get("filename"),
                        att.get("content_type"),
                        att.get("size"),
                        att.get("data"),  # bytes or None
                    ),
                )

        conn.commit()
        return email_id

    def update_sync_state(self, folder: str, last_uid: int) -> None:
        conn = self._conn()
        conn.execute(
            """
            INSERT INTO sync_state (folder, last_uid, synced_at)
            VALUES (?,?,?)
            ON CONFLICT(folder) DO UPDATE SET
                last_uid  = excluded.last_uid,
                synced_at = excluded.synced_at
            """,
            (folder, last_uid, datetime.utcnow().isoformat()),
        )
        conn.commit()

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_last_uid(self, folder: str) -> int:
        row = (
            self._conn()
            .execute("SELECT last_uid FROM sync_state WHERE folder=?", (folder,))
            .fetchone()
        )
        return int(row["last_uid"]) if row else 0

    def search_fts(
        self,
        query: str,
        folder: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Full-text search via FTS5. Returns matching email rows."""
        if folder:
            rows = (
                self._conn()
                .execute(
                    """
                SELECT e.*,
                       snippet(emails_fts, 4, '**', '**', '...', 15) AS snippet
                FROM   emails_fts
                JOIN   emails e ON e.id = emails_fts.rowid
                WHERE  emails_fts MATCH ?
                  AND  e.folder = ?
                ORDER BY rank
                LIMIT ?
                """,
                    (query, folder, limit),
                )
                .fetchall()
            )
        else:
            rows = (
                self._conn()
                .execute(
                    """
                SELECT e.*,
                       snippet(emails_fts, 4, '**', '**', '...', 15) AS snippet
                FROM   emails_fts
                JOIN   emails e ON e.id = emails_fts.rowid
                WHERE  emails_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                    (query, limit),
                )
                .fetchall()
            )
        return [dict(r) for r in rows]

    def get_stats(self) -> dict:
        """Return DB statistics for the sync_status tool."""
        conn = self._conn()
        total = conn.execute("SELECT COUNT(*) FROM emails").fetchone()[0]
        by_folder = conn.execute(
            "SELECT folder, COUNT(*) AS cnt FROM emails GROUP BY folder"
        ).fetchall()
        sync_states = conn.execute("SELECT folder, last_uid, synced_at FROM sync_state").fetchall()
        total_att = conn.execute("SELECT COUNT(*) FROM attachments").fetchone()[0]
        return {
            "total_emails": total,
            "total_attachments": total_att,
            "by_folder": {r["folder"]: r["cnt"] for r in by_folder},
            "sync_state": [dict(r) for r in sync_states],
        }

    def get_email_by_db_id(self, email_id: int) -> dict | None:
        row = self._conn().execute("SELECT * FROM emails WHERE id=?", (email_id,)).fetchone()
        return dict(row) if row else None

    def get_attachments_meta(self, email_id: int) -> list[dict]:
        """Attachment metadata (no binary data)."""
        rows = (
            self._conn()
            .execute(
                "SELECT id, filename, content_type, size FROM attachments WHERE email_id=?",
                (email_id,),
            )
            .fetchall()
        )
        return [dict(r) for r in rows]

    def get_attachment_by_uid(
        self,
        folder: str,
        uid: int,
        filename: str | None = None,
    ) -> dict | None:
        """Return attachment with binary data for a given email UID.

        If *filename* is provided, returns the matching attachment.
        Otherwise returns the first attachment found.
        Returns None when the email or attachment is not in the DB
        (caller should fall back to live IMAP).
        """
        conn = self._conn()
        email_row = conn.execute(
            "SELECT id FROM emails WHERE folder=? AND uid=?", (folder, uid)
        ).fetchone()
        if not email_row:
            return None
        email_id = email_row["id"]

        if filename:
            row = conn.execute(
                "SELECT id, filename, content_type, size, data "
                "FROM attachments WHERE email_id=? AND filename=?",
                (email_id, filename),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id, filename, content_type, size, data "
                "FROM attachments WHERE email_id=? LIMIT 1",
                (email_id,),
            ).fetchone()

        if row is None or row["data"] is None:
            # Row exists but binary data not yet synced → fall back to IMAP
            return None

        return {
            "uid": str(uid),
            "filename": row["filename"],
            "content_type": row["content_type"],
            "size": row["size"],
            "data_base64": base64.b64encode(row["data"]).decode("ascii"),
        }

    def list_emails(
        self,
        folder: str | None = None,
        limit: int = 50,
        offset: int = 0,
        unread_only: bool = False,
    ) -> list[dict]:
        where = []
        params: list = []
        if folder:
            where.append("folder=?")
            params.append(folder)
        if unread_only:
            where.append("is_read=0")
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        params += [limit, offset]
        rows = (
            self._conn()
            .execute(
                f"SELECT id, folder, uid, subject, from_addr, to_addr, date_str, "
                f"is_read, is_flagged, has_attachments "
                f"FROM emails {clause} ORDER BY uid DESC LIMIT ? OFFSET ?",
                params,
            )
            .fetchall()
        )
        return [dict(r) for r in rows]
