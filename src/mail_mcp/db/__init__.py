"""SQLite email store with FTS5 full-text search and background IMAP sync."""

from .store import EmailStore, get_email_store, init_email_store
from .sync import EmailSyncer

__all__ = ["EmailStore", "get_email_store", "init_email_store", "EmailSyncer"]
