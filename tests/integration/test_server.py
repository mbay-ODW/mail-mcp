"""
Integration tests for IMAP MCP Server.

These tests require real IMAP credentials configured via environment variables:
- IMAP_HOST: IMAP server hostname
- IMAP_PORT: IMAP server port (default: 993)
- EMAIL_USER: Email username
- EMAIL_PASSWORD: Email password
- IMAP_SSL: Use SSL (default: true)

Run with: pytest tests/integration/test_server.py -v
"""

import os
import pytest
from unittest.mock import Mock, patch, MagicMock

# Import server components
from imap_mcp.server import (
    IMAPConfig,
    IMAPClient,
    get_imap_client,
    reset_imap_client,
    app,
)


class TestIMAPConfig:
    """Test IMAP configuration."""

    def test_config_from_env_defaults(self):
        """Test default configuration values."""
        with patch.dict(os.environ, {}, clear=True):
            config = IMAPConfig.from_env()
            assert config.host == "imap.example.com"
            assert config.port == 993
            assert config.user == ""
            assert config.password == ""
            assert config.ssl is True

    def test_config_from_env_custom(self):
        """Test custom configuration values."""
        env = {
            "IMAP_HOST": "mail.test.com",
            "IMAP_PORT": "994",
            "EMAIL_USER": "testuser",
            "EMAIL_PASSWORD": "testpass",
            "IMAP_SSL": "false",
        }
        with patch.dict(os.environ, env, clear=True):
            config = IMAPConfig.from_env()
            assert config.host == "mail.test.com"
            assert config.port == 994
            assert config.user == "testuser"
            assert config.password == "testpass"
            assert config.ssl is False


class TestIMAPClient:
    """Test IMAP client functionality."""

    @pytest.fixture(autouse=True)
    def reset_client(self):
        """Reset client before each test."""
        reset_imap_client()
        yield
        reset_imap_client()

    @pytest.fixture
    def mock_imap_connection(self):
        """Create mock IMAP connection."""
        with patch("imap_mcp.server.imaplib.IMAP4_SSL") as mock_ssl:
            mock_conn = MagicMock()
            mock_ssl.return_value = mock_conn
            yield mock_conn

    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return IMAPConfig(
            host="imap.test.com",
            port=993,
            user="test@test.com",
            password="testpass",
        )

    def test_connect(self, config, mock_imap_connection):
        """Test IMAP connection."""
        client = IMAPClient(config)
        client.connect()

        mock_imap_connection.login.assert_called_once_with(
            config.user, config.password
        )

    def test_list_folders(self, config, mock_imap_connection):
        """Test listing folders."""
        mock_imap_connection.list.return_value = (
            b"OK",
            [b'(\\HasNoChildren) "/" "INBOX"'],
        )

        client = IMAPClient(config)
        client.connect()
        folders = client.list_folders()

        assert len(folders) >= 1

    def test_create_folder(self, config, mock_imap_connection):
        """Test creating a folder."""
        mock_imap_connection.create.return_value = (b"OK", [b"Success"])

        client = IMAPClient(config)
        client.connect()
        result = client.create_folder("TestFolder")

        assert result["success"] is True
        assert result["folder"] == "TestFolder"

    def test_delete_folder(self, config, mock_imap_connection):
        """Test deleting a folder."""
        mock_imap_connection.delete.return_value = (b"OK", [b"Success"])

        client = IMAPClient(config)
        client.connect()
        result = client.delete_folder("TestFolder")

        assert result["success"] is True

    def test_rename_folder(self, config, mock_imap_connection):
        """Test renaming a folder."""
        mock_imap_connection.rename.return_value = (b"OK", [b"Success"])

        client = IMAPClient(config)
        client.connect()
        result = client.rename_folder("OldName", "NewName")

        assert result["success"] is True
        assert result["old_name"] == "OldName"
        assert result["new_name"] == "NewName"

    def test_search_emails(self, config, mock_imap_connection):
        """Test searching emails."""
        # Mock select
        mock_imap_connection.select.return_value = (b"OK", [b"100"])

        # Mock search
        mock_imap_connection.search.return_value = (
            b"OK",
            [b"1 2 3 4 5"],
        )

        # Mock fetch with proper envelope data
        envelope_data = (
            b'1 (UID 12345 FLAGS (\\Seen) ENVELOPE '
            b'"(Thu, 14 Mar 2024 10:00:00 +0000)" '
            b'"Test Subject" (("Sender" NIL "sender" "test.com")) '
            b'NIL NIL NIL "<test@test.com>")'
        )
        mock_imap_connection.fetch.return_value = (b"OK", [envelope_data])

        client = IMAPClient(config)
        client.connect()
        results = client.search_emails(criteria="UNSEEN", limit=3)

        assert isinstance(results, list)

    def test_get_email(self, config, mock_imap_connection):
        """Test getting email details."""
        # Mock select
        mock_imap_connection.select.return_value = (b"OK", [b"100"])

        # Mock fetch
        envelope_data = (
            b'1 (UID 12345 FLAGS (\\Seen) ENVELOPE '
            b'"(Thu, 14 Mar 2024 10:00:00 +0000)" '
            b'"Test Subject" (("Sender" NIL "sender" "test.com")) '
            b'NIL NIL NIL "<test@test.com>")'
        )
        mock_imap_connection.fetch.return_value = (b"OK", [envelope_data])

        client = IMAPClient(config)
        client.connect()
        result = client.get_email(message_id="1")

        assert result["uid"] == "12345"
        assert result["subject"] == "Test Subject"

    def test_mark_read(self, config, mock_imap_connection):
        """Test marking email as read."""
        # Mock select
        mock_imap_connection.select.return_value = (b"OK", [b"100"])

        # Mock store
        mock_imap_connection.store.return_value = (b"OK", [b"Success"])

        client = IMAPClient(config)
        client.connect()
        result = client.mark_read(message_id="1")

        assert result["success"] is True
        assert result["flag"] == "\\Seen"

    def test_mark_unread(self, config, mock_imap_connection):
        """Test marking email as unread."""
        mock_imap_connection.select.return_value = (b"OK", [b"100"])
        mock_imap_connection.store.return_value = (b"OK", [b"Success"])

        client = IMAPClient(config)
        client.connect()
        result = client.mark_unread(message_id="1")

        assert result["success"] is True

    def test_mark_flagged(self, config, mock_imap_connection):
        """Test marking email as flagged."""
        mock_imap_connection.select.return_value = (b"OK", [b"100"])
        mock_imap_connection.store.return_value = (b"OK", [b"Success"])

        client = IMAPClient(config)
        client.connect()
        result = client.mark_flagged(message_id="1")

        assert result["success"] is True
        assert result["flag"] == "\\Flagged"

    def test_unmark_flagged(self, config, mock_imap_connection):
        """Test unmarking email as flagged."""
        mock_imap_connection.select.return_value = (b"OK", [b"100"])
        mock_imap_connection.store.return_value = (b"OK", [b"Success"])

        client = IMAPClient(config)
        client.connect()
        result = client.unmark_flagged(message_id="1")

        assert result["success"] is True

    def test_move_email(self, config, mock_imap_connection):
        """Test moving email to another folder."""
        mock_imap_connection.select.return_value = (b"OK", [b"100"])
        mock_imap_connection.move.return_value = (b"OK", [b"Success"])

        client = IMAPClient(config)
        client.connect()
        result = client.move_email("INBOX", "Archive", message_id="1")

        assert result["success"] is True
        assert result["target_folder"] == "Archive"

    def test_copy_email(self, config, mock_imap_connection):
        """Test copying email to another folder."""
        mock_imap_connection.select.return_value = (b"OK", [b"100"])
        mock_imap_connection.copy.return_value = (b"OK", [b"Success"])

        client = IMAPClient(config)
        client.connect()
        result = client.copy_email("INBOX", "Archive", message_id="1")

        assert result["success"] is True

    def test_delete_email(self, config, mock_imap_connection):
        """Test deleting email."""
        mock_imap_connection.select.return_value = (b"OK", [b"100"])
        mock_imap_connection.store.return_value = (b"OK", [b"Success"])
        mock_imap_connection.expunge.return_value = (b"OK", [b"Success"])

        client = IMAPClient(config)
        client.connect()
        result = client.delete_email(message_id="1")

        assert result["success"] is True

    def test_get_current_date(self, config, mock_imap_connection):
        """Test getting current date."""
        client = IMAPClient(config)
        result = client.get_current_date()

        # Should be ISO format date string
        assert "T" in result  # ISO format contains 'T'
        assert "-" in result  # ISO format contains date separators


class TestMCPTools:
    """Test MCP server tools."""

    def test_list_tools_returns_all_tools(self):
        """Verify all tools are registered."""
        # Get tools by calling list_tools function directly
        tools = list_tools()
        tool_names = [t.name for t in tools]

        expected_tools = [
            "list_folders",
            "create_folder",
            "delete_folder",
            "rename_folder",
            "search_emails",
            "get_email",
            "mark_read",
            "mark_unread",
            "mark_flagged",
            "unmark_flagged",
            "move_email",
            "copy_email",
            "delete_email",
            "get_current_date",
        ]

        for name in expected_tools:
            assert name in tool_names, f"Missing tool: {name}"


class TestIntegration:
    """Integration tests that simulate real workflows."""

    @pytest.fixture(autouse=True)
    def reset_client(self):
        """Reset client before each test."""
        reset_imap_client()
        yield
        reset_imap_client()

    def test_full_email_workflow(self):
        """Test complete email management workflow."""
        # This test simulates a full workflow with mocked IMAP
        with patch("imap_mcp.server.imaplib.IMAP4_SSL") as mock_ssl:
            mock_conn = MagicMock()
            mock_ssl.return_value = mock_conn

            # Set up mock responses
            mock_conn.list.return_value = (
                b"OK",
                [b'(\\HasNoChildren) "/" "INBOX"'],
            )
            mock_conn.create.return_value = (b"OK", [b"Success"])
            mock_conn.select.return_value = (b"OK", [b"10"])
            mock_conn.search.return_value = (b"OK", [b"1"])
            mock_conn.fetch.return_value = (
                b"OK",
                [
                    b'1 (UID 100 FLAGS (\\Seen) ENVELOPE '
                    b'"(Thu, 14 Mar 2024 10:00:00 +0000)" '
                    b'"Test" (("Sender" NIL "sender" "test.com")) '
                    b'NIL NIL NIL "<test@test.com>")'
                ],
            )
            mock_conn.store.return_value = (b"OK", [b"Success"])
            mock_conn.move.return_value = (b"OK", [b"Success"])
            mock_conn.delete.return_value = (b"OK", [b"Success"])

            # Create client and connect
            config = IMAPConfig(
                host="imap.test.com",
                port=993,
                user="test@test.com",
                password="pass",
            )
            client = IMAPClient(config)
            client.connect()

            # List folders
            folders = client.list_folders()
            assert len(folders) >= 1

            # Create folder
            result = client.create_folder("Work")
            assert result["success"]

            # Search emails
            emails = client.search_emails(criteria="ALL", limit=5)
            assert isinstance(emails, list)

            # Get email
            if emails:
                email_data = client.get_email(
                    folder="INBOX",
                    message_id=emails[0].get("id", "1")
                )
                assert "subject" in email_data

            # Mark as read
            result = client.mark_read(message_id="1")
            assert result["success"]

            # Move to folder
            result = client.move_email("INBOX", "Archive", message_id="1")
            assert result["success"]

            # Delete
            result = client.delete_email(message_id="1")
            assert result["success"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])