"""Configuration module for IMAP MCP Server."""

import os
from dataclasses import dataclass, field


@dataclass
class IMAPConfig:
    """IMAP configuration from environment variables."""

    host: str
    port: int
    user: str
    password: str
    ssl: bool = True

    @classmethod
    def from_env(cls) -> "IMAPConfig":
        """Create config from environment variables."""
        return cls(
            host=os.getenv("IMAP_HOST", "imap.example.com"),
            port=int(os.getenv("IMAP_PORT", "993")),
            user=os.getenv("EMAIL_USER", ""),
            password=os.getenv("EMAIL_PASSWORD", ""),
            ssl=os.getenv("IMAP_SSL", "true").lower() == "true",
        )


@dataclass
class DBConfig:
    """SQLite email cache configuration from environment variables.

    Set EMAIL_DB_ENABLED=true to activate the local email database.
    All emails are synced from IMAP into a SQLite store with FTS5
    full-text search.

    Environment variables:
        EMAIL_DB_ENABLED        – Enable DB cache (default: false)
        EMAIL_DB_PATH           – Path to SQLite file (default: /data/mail.db)
        EMAIL_DB_SYNC_INTERVAL  – Sync interval in seconds (default: 300)
        EMAIL_DB_SYNC_DAYS      – Days of history on initial sync (default: 90)
    """

    enabled: bool = False
    path: str = "/data/mail.db"
    sync_interval: int = 300
    sync_days: int = 90

    @classmethod
    def from_env(cls) -> "DBConfig":
        return cls(
            enabled=os.getenv("EMAIL_DB_ENABLED", "false").lower() == "true",
            path=os.getenv("EMAIL_DB_PATH", "/data/mail.db"),
            sync_interval=int(os.getenv("EMAIL_DB_SYNC_INTERVAL", "300")),
            sync_days=int(os.getenv("EMAIL_DB_SYNC_DAYS", "90")),
        )


__all__ = ["IMAPConfig", "DBConfig"]
