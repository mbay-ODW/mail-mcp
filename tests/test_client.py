"""Tests for IMAP client."""

from unittest.mock import Mock, patch

import pytest

from mail_mcp.client import IMAP_OK, IMAPClient
from mail_mcp.config import IMAPConfig


class TestIMAPClient:
    """Test cases for IMAPClient."""

    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return IMAPConfig(
            host="imap.example.com",
            port=993,
            user="test@example.com",
            password="password",
        )

    @pytest.fixture
    def client(self, config):
        """Create test client."""
        return IMAPClient(config)

    def test_client_initialization(self, client, config):
        """Test client initialization."""
        assert client.config == config
        assert client._connection is None

    def test_imap_ok_constant(self):
        """Test IMAP_OK constant."""
        assert b"OK" in IMAP_OK
        assert "OK" in IMAP_OK

    @patch("mail_mcp.client.imaplib.IMAP4_SSL")
    def test_connect_ssl(self, mock_imap_ssl, client):
        """Test SSL connection."""
        mock_conn = Mock()
        mock_imap_ssl.return_value = mock_conn

        client.connect()

        mock_imap_ssl.assert_called_once_with(
            host="imap.example.com",
            port=993,
        )
        mock_conn.login.assert_called_once_with("test@example.com", "password")

    def test_disconnect(self, client):
        """Test disconnection."""
        client._connection = Mock()
        client.disconnect()

        assert client._connection is None

    def test_disconnect_with_error(self, client):
        """Test disconnection handles errors gracefully."""
        mock_conn = Mock()
        mock_conn.logout.side_effect = Exception("Connection closed")
        client._connection = mock_conn

        # Should not raise
        client.disconnect()

        assert client._connection is None
