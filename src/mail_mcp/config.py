"""Configuration module for IMAP MCP Server."""

import os
from dataclasses import dataclass


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


@dataclass
class TransferConfig:
    """Configuration for direct server-to-server attachment transfers.

    When PAPERLESS_URL + PAPERLESS_API_KEY are set, the tool
    'transfer_to_paperless' becomes available.
    When HERO_API_KEY is set, the tool 'transfer_to_hero' becomes available.

    Environment variables:
        PAPERLESS_URL           – Internal Paperless base URL (e.g. http://webserver:8000)
        PAPERLESS_API_KEY       – Paperless API token
        HERO_API_KEY            – HERO Bearer token
        HERO_GRAPHQL_URL        – HERO GraphQL endpoint (has a default)
        ATTACHMENT_MAX_SIZE_KB  – Max attachment size for get_attachment include_data=true (default: 50)
    """

    paperless_url: str = ""
    paperless_api_key: str = ""
    hero_api_key: str = ""
    hero_graphql_url: str = "https://login.hero-software.de/api/external/v7/graphql"
    attachment_max_size_kb: int = 50

    @classmethod
    def from_env(cls) -> "TransferConfig":
        return cls(
            paperless_url=os.getenv("PAPERLESS_URL", "").rstrip("/"),
            paperless_api_key=os.getenv("PAPERLESS_API_KEY", ""),
            hero_api_key=os.getenv("HERO_API_KEY", ""),
            hero_graphql_url=os.getenv(
                "HERO_GRAPHQL_URL",
                "https://login.hero-software.de/api/external/v7/graphql",
            ),
            attachment_max_size_kb=int(os.getenv("ATTACHMENT_MAX_SIZE_KB", "50")),
        )

    @property
    def paperless_enabled(self) -> bool:
        return bool(self.paperless_url and self.paperless_api_key)

    @property
    def hero_enabled(self) -> bool:
        return bool(self.hero_api_key)


__all__ = ["IMAPConfig", "DBConfig", "TransferConfig"]
