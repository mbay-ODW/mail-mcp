"""Tests for IMAP configuration."""

import os
import pytest
from unittest.mock import patch

from imap_mcp.config import IMAPConfig


class TestIMAPConfig:
    """Test cases for IMAPConfig."""

    def test_default_values(self):
        """Test default configuration values."""
        config = IMAPConfig(
            host="imap.example.com",
            port=993,
            user="test@example.com",
            password="password",
        )
        assert config.host == "imap.example.com"
        assert config.port == 993
        assert config.user == "test@example.com"
        assert config.password == "password"
        assert config.ssl is True

    def test_from_env(self):
        """Test creating config from environment variables."""
        with patch.dict(os.environ, {
            "IMAP_HOST": "imap.test.com",
            "IMAP_PORT": "993",
            "EMAIL_USER": "user@test.com",
            "EMAIL_PASSWORD": "secret",
            "IMAP_SSL": "true",
        }):
            config = IMAPConfig.from_env()
            assert config.host == "imap.test.com"
            assert config.port == 993
            assert config.user == "user@test.com"
            assert config.password == "secret"
            assert config.ssl is True

    def test_from_env_ssl_false(self):
        """Test SSL disabled from environment."""
        with patch.dict(os.environ, {
            "IMAP_HOST": "imap.test.com",
            "IMAP_PORT": "143",
            "EMAIL_USER": "user@test.com",
            "EMAIL_PASSWORD": "secret",
            "IMAP_SSL": "false",
        }):
            config = IMAPConfig.from_env()
            assert config.ssl is False
            assert config.port == 143