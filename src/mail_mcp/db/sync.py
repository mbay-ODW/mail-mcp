"""
Background IMAP → SQLite sync thread.

On first run: fetches all emails from the last EMAIL_DB_SYNC_DAYS days.
Subsequently: fetches only emails with UID > last known UID (incremental).
"""

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .store import EmailStore


class EmailSyncer:
    """Daemon thread that keeps the SQLite store in sync with IMAP."""

    def __init__(
        self,
        store: "EmailStore",
        sync_interval: int = 300,
        sync_days: int = 90,
    ) -> None:
        self._store = store
        self._interval = sync_interval
        self._sync_days = sync_days
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_error: str | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="email-syncer"
        )
        self._thread.start()
        logging.info(
            "EmailSyncer started (interval=%ds, initial_days=%d)",
            self._interval,
            self._sync_days,
        )

    def stop(self) -> None:
        self._stop.set()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------
    # Sync loop
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        self._sync_all()
        while not self._stop.wait(self._interval):
            self._sync_all()

    def _sync_all(self) -> None:
        # Import here to avoid circular imports at module load time
        from ..client import get_imap_client

        try:
            client = get_imap_client()
            folders = client.list_folders()
            for folder_info in folders:
                if isinstance(folder_info, dict):
                    folder = folder_info.get("name", "")
                else:
                    folder = str(folder_info)
                if folder:
                    self._sync_folder(client, folder)
            self._last_error = None
        except Exception as exc:
            self._last_error = str(exc)
            logging.error("EmailSyncer._sync_all error: %s", exc)

    def _sync_folder(self, client, folder: str) -> None:
        from ..client import get_imap_client  # noqa: F401 (kept for type clarity)

        try:
            last_uid = self._store.get_last_uid(folder)

            if last_uid == 0:
                # Initial sync – fetch last N days
                since = (datetime.now() - timedelta(days=self._sync_days)).strftime(
                    "%d-%b-%Y"
                )
                criteria = f"SINCE {since}"
            else:
                # Incremental – UID greater than last seen
                criteria = f"UID {last_uid + 1}:*"

            summaries = client.search_emails(
                folder=folder, criteria=criteria, limit=500
            )
            if not summaries:
                return

            new_last_uid = last_uid
            synced = 0

            for summary in summaries:
                raw_uid = summary.get("uid") or summary.get("id")
                if raw_uid is None:
                    continue
                try:
                    uid = int(raw_uid)
                except (ValueError, TypeError):
                    continue

                # Skip if already indexed (incremental mode may still return known UIDs)
                if uid <= last_uid:
                    continue

                try:
                    full = client.get_email(
                        folder=folder, uid=str(uid), include_body=True
                    )
                    if not full:
                        continue

                    flags = full.get("flags", [])
                    is_read = any(
                        f.lower() in ("\\seen", "seen") for f in flags
                    )
                    is_flagged = any(
                        f.lower() in ("\\flagged", "flagged") for f in flags
                    )

                    # Attachment metadata only (no binary to keep DB lean)
                    att_meta = [
                        {
                            "filename": a.get("filename"),
                            "content_type": a.get("content_type"),
                            "size": a.get("size"),
                            "data": None,
                        }
                        for a in full.get("attachments", [])
                    ]

                    self._store.upsert_email(
                        folder=folder,
                        uid=uid,
                        message_id=full.get("message_id"),
                        subject=full.get("subject"),
                        from_addr=full.get("from"),
                        to_addr=full.get("to"),
                        cc_addr=full.get("cc"),
                        date_str=str(full.get("date", "")),
                        body_text=full.get("body_text") or "",
                        body_html=full.get("body_html") or "",
                        is_read=is_read,
                        is_flagged=is_flagged,
                        attachments=att_meta if att_meta else None,
                    )

                    new_last_uid = max(new_last_uid, uid)
                    synced += 1

                except Exception as exc:
                    logging.warning(
                        "EmailSyncer: skipped uid=%s folder=%s – %s", uid, folder, exc
                    )

            if new_last_uid > last_uid:
                self._store.update_sync_state(folder, new_last_uid)

            if synced:
                logging.info(
                    "EmailSyncer: synced %d emails in '%s' (last_uid=%d)",
                    synced,
                    folder,
                    new_last_uid,
                )

        except Exception as exc:
            logging.error("EmailSyncer: folder '%s' error – %s", folder, exc)
