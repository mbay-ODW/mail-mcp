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


__all__ = ["IMAPConfig"]
