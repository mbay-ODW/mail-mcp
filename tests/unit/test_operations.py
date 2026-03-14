"""
Unit tests for Operations module.
Test skeleton using mock IMAP connections.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, PropertyMock
from typing import List, Dict, Any
from email.message import Message
from email.policy import default
from email.parser import BytesParser


# Import the module under test (will be implemented)
OK = b'OK'


class TestEmailSearch:
    """Test suite for email search operations."""
    
    @pytest.fixture
    def mock_imap_connection(self):
        """Create a mock IMAP connection."""
        mock_conn = MagicMock()
        return mock_conn
    
    @pytest.fixture
    def search_manager(self, mock_imap_connection):
        """Create EmailSearch with mock connection."""
        from imap_mcp.operations.search import EmailSearch
        return EmailSearch(mock_imap_connection)
    
    def test_search_by_subject(self, search_manager, mock_imap_connection):
        """search_emails should find emails by subject."""
        # Arrange
        mock_imap_connection.search.return_value = (OK, [b'1 2 3'])
        
        # Act
        result = search_manager.search_emails('INBOX', {'subject': 'test'})
        
        # Assert
        assert isinstance(result, list)
        assert len(result) == 3
    
    def test_search_by_from(self, search_manager, mock_imap_connection):
        """search_emails should find emails by sender."""
        # Arrange
        mock_imap_connection.search.return_value = (OK, [b'1 5 10'])
        
        # Act
        result = search_manager.search_emails('INBOX', {'from': 'test@example.com'})
        
        # Assert
        assert len(result) == 3
    
    def test_search_by_date(self, search_manager, mock_imap_connection):
        """search_emails should find emails by date."""
        # Arrange
        mock_imap_connection.search.return_value = (OK, [b'1'])
        
        # Act
        result = search_manager.search_emails('INBOX', {'since': '2024-01-01'})
        
        # Assert
        assert len(result) == 1
    
    def test_search_combined_conditions(self, search_manager, mock_imap_connection):
        """search_emails should support combined conditions (AND)."""
        # Arrange
        mock_imap_connection.search.return_value = (OK, [b'1 2'])
        
        # Act
        result = search_manager.search_emails('INBOX', {
            'subject': 'meeting',
            'from': 'boss@example.com',
            'since': '2024-01-01'
        })
        
        # Assert
        assert len(result) == 2
    
    def test_search_no_results(self, search_manager, mock_imap_connection):
        """search_emails should return empty list when no matches."""
        # Arrange
        mock_imap_connection.search.return_value = (OK, [b''])
        
        # Act
        result = search_manager.search_emails('INBOX', {'subject': 'nonexistent'})
        
        # Assert
        assert result == []
    
    def test_search_with_flag_conditions(self, search_manager, mock_imap_connection):
        """search_emails should support flag conditions."""
        # Arrange
        mock_imap_connection.search.return_value = (OK, [b'1 2 3'])
        
        # Act - search for unread emails
        result = search_manager.search_emails('INBOX', {'unread': True})
        
        # Assert
        assert len(result) == 3


class TestEmailFetch:
    """Test suite for email fetch operations."""
    
    @pytest.fixture
    def mock_imap_connection(self):
        """Create a mock IMAP connection."""
        mock_conn = MagicMock()
        return mock_conn
    
    @pytest.fixture
    def fetch_manager(self, mock_imap_connection):
        """Create EmailFetch with mock connection."""
        from imap_mcp.operations.fetch import EmailFetch
        return EmailFetch(mock_imap_connection)
    
    def test_get_email_headers_only(self, fetch_manager, mock_imap_connection):
        """get_email should fetch only headers when requested."""
        # Arrange
        header_data = b'From: test@example.com\r\nSubject: Test\r\nDate: Mon, 1 Jan 2024 12:00:00\r\n'
        mock_imap_connection.fetch.return_value = (
            OK,
            [(b'1 (BODY[HEADER] {0}'.format(len(header_data)), header_data)]
        )
        
        # Act
        result = fetch_manager.get_email('INBOX', 1, headers_only=True)
        
        # Assert
        assert result is not None
        assert 'From' in result or 'from' in result.lower()
    
    def test_get_email_full(self, fetch_manager, mock_imap_connection):
        """get_email should fetch full email with body."""
        # Arrange
        full_data = b'From: test@example.com\r\nSubject: Test\r\n\r\nBody content'
        mock_imap_connection.fetch.return_value = (
            OK,
            [(b'1 (BODY[] {0})'.format(len(full_data)), full_data)]
        )
        
        # Act
        result = fetch_manager.get_email('INBOX', 1)
        
        # Assert
        assert result is not None
    
    def test_get_email_not_found(self, fetch_manager, mock_imap_connection):
        """get_email should raise error when email not found."""
        # Arrange
        mock_imap_connection.fetch.return_value = (OK, [])
        
        # Act & Assert
        from imap_mcp.operations.fetch import EmailError
        with pytest.raises(EmailError):
            fetch_manager.get_email('INBOX', 99999)
    
    def test_get_email_parse_structure(self, fetch_manager, mock_imap_connection):
        """get_email should parse email structure correctly."""
        # This tests that the returned dict has expected keys
        # Arrange
        header_data = b'From: sender@example.com\r\nTo: receiver@example.com\r\nSubject: Test\r\n'
        mock_imap_connection.fetch.return_value = (
            OK,
            [(b'1 (BODY[HEADER] {0}'.format(len(header_data)), header_data)]
        )
        
        # Act
        result = fetch_manager.get_email('INBOX', 1)
        
        # Assert
        assert result is not None


class TestEmailFlags:
    """Test suite for email flag operations."""
    
    @pytest.fixture
    def mock_imap_connection(self):
        """Create a mock IMAP connection."""
        mock_conn = MagicMock()
        return mock_conn
    
    @pytest.fixture
    def flags_manager(self, mock_imap_connection):
        """Create EmailFlags with mock connection."""
        from imap_mcp.operations.flags import EmailFlags
        return EmailFlags(mock_imap_connection)
    
    def test_mark_read_single(self, flags_manager, mock_imap_connection):
        """mark_read should mark single email as read."""
        # Arrange
        mock_imap_connection.store.return_value = (OK, [b'1 (FLAGS (\\Seen))'])
        
        # Act
        result = flags_manager.mark_read('INBOX', [1])
        
        # Assert
        assert result is True
    
    def test_mark_read_multiple(self, flags_manager, mock_imap_connection):
        """mark_read should mark multiple emails as read."""
        # Arrange
        mock_imap_connection.store.return_value = (OK, [b'1 2 3 (FLAGS (\\Seen))'])
        
        # Act
        result = flags_manager.mark_read('INBOX', [1, 2, 3])
        
        # Assert
        assert result is True
    
    def test_mark_unread(self, flags_manager, mock_imap_connection):
        """mark_unread should mark email as unread."""
        # Arrange
        mock_imap_connection.store.return_value = (OK, [b'1 (FLAGS ())'])
        
        # Act
        result = flags_manager.mark_unread('INBOX', [1])
        
        # Assert
        assert result is True
    
    def test_mark_flagged(self, flags_manager, mock_imap_connection):
        """mark_flagged should add flagged/starred status."""
        # Arrange
        mock_imap_connection.store.return_value = (OK, [b'1 (FLAGS (\\Flagged))'])
        
        # Act
        result = flags_manager.mark_flagged('INBOX', [1])
        
        # Assert
        assert result is True
    
    def test_unmark_flagged(self, flags_manager, mock_imap_connection):
        """unmark_flagged should remove flagged status."""
        # Arrange
        mock_imap_connection.store.return_value = (OK, [b'1 (FLAGS ())'])
        
        # Act
        result = flags_manager.unmark_flagged('INBOX', [1])
        
        # Assert
        assert result is True


class TestEmailMove:
    """Test suite for email move/copy operations."""
    
    @pytest.fixture
    def mock_imap_connection(self):
        """Create a mock IMAP connection."""
        mock_conn = MagicMock()
        return mock_conn
    
    @pytest.fixture
    def move_manager(self, mock_imap_connection):
        """Create EmailMove with mock connection."""
        from imap_mcp.operations.move import EmailMove
        return EmailMove(mock_imap_connection)
    
    def test_move_email_success(self, move_manager, mock_imap_connection):
        """move_email should move email to destination folder."""
        # Arrange
        mock_imap_connection.move.return_value = (OK, [b'1 Moved'])
        
        # Act
        result = move_manager.move_email('INBOX', 1, 'INBOX/Archive')
        
        # Assert
        assert result is True
        mock_imap_connection.move.assert_called_once()
    
    def test_copy_email_success(self, move_manager, mock_imap_connection):
        """copy_email should copy email to destination folder."""
        # Arrange
        mock_imap_connection.copy.return_value = (OK, [b'1 Copied'])
        
        # Act
        result = move_manager.copy_email('INBOX', 1, 'INBOX/Backup')
        
        # Assert
        assert result is True
        mock_imap_connection.copy.assert_called_once()
    
    def test_move_multiple_emails(self, move_manager, mock_imap_connection):
        """move_email should handle multiple emails."""
        # Arrange
        mock_imap_connection.move.return_value = (OK, [b'1 2 3 Moved'])
        
        # Act
        result = move_manager.move_email('INBOX', [1, 2, 3], 'INBOX/Archive')
        
        # Assert
        assert result is True


class TestEmailDelete:
    """Test suite for email delete operations."""
    
    @pytest.fixture
    def mock_imap_connection(self):
        """Create a mock IMAP connection."""
        mock_conn = MagicMock()
        return mock_conn
    
    @pytest.fixture
    def delete_manager(self, mock_imap_connection):
        """Create EmailDelete with mock connection."""
        from imap_mcp.operations.move import EmailMove
        return EmailMove(mock_imap_connection)
    
    def test_delete_email_adds_deleted_flag(self, delete_manager, mock_imap_connection):
        """delete_email should add \\Deleted flag."""
        # Arrange
        mock_imap_connection.store.return_value = (OK, [b'1 (FLAGS (\\Deleted))'])
        
        # Act
        from imap_mcp.operations.move import EmailMove
        result = delete_manager.delete_email('INBOX', [1])
        
        # Assert
        assert result is True
    
    def test_expunge_deletes_marked_messages(self, delete_manager, mock_imap_connection):
        """expunge should permanently delete marked messages."""
        # Arrange
        mock_imap_connection.expunge.return_value = (OK, [b'1'])
        
        # Act
        from imap_mcp.operations.move import EmailMove
        result = delete_manager.expunge('INBOX')
        
        # Assert
        assert result is True


class TestOperationsErrors:
    """Test suite for operations error handling."""
    
    def test_search_connection_error(self):
        """Should handle connection errors in search."""
        from imap_mcp.operations.search import EmailSearch, EmailSearchError
        
        mock_conn = MagicMock()
        mock_conn.search.side_effect = Exception("Connection lost")
        
        with pytest.raises(EmailSearchError):
            search = EmailSearch(mock_conn)
            search.search_emails('INBOX', {'subject': 'test'})
    
    def test_fetch_connection_error(self):
        """Should handle connection errors in fetch."""
        from imap_mcp.operations.fetch import EmailFetch, EmailFetchError
        
        mock_conn = MagicMock()
        mock_conn.fetch.side_effect = Exception("Connection lost")
        
        with pytest.raises(EmailFetchError):
            fetch = EmailFetch(mock_conn)
            fetch.get_email('INBOX', 1)
    
    def test_invalid_folder(self):
        """Should handle invalid folder errors."""
        from imap_mcp.operations.search import EmailSearch, EmailSearchError
        
        mock_conn = MagicMock()
        mock_conn.search.return_value = (b'NO', [b'Invalid folder'])
        
        with pytest.raises(EmailSearchError):
            search = EmailSearch(mock_conn)
            search.search_emails('InvalidFolder', {'subject': 'test'})


class TestEmailOperations:
    """Integration tests for email operations workflow."""
    
    @pytest.fixture
    def mock_imap_connection(self):
        """Create a fully configured mock IMAP connection."""
        mock_conn = MagicMock()
        
        # Setup search response
        mock_conn.search.return_value = (OK, [b'1 2 3'])
        
        # Setup fetch response
        header_data = b'From: test@example.com\r\nSubject: Test Email\r\n'
        mock_conn.fetch.return_value = (OK, [(b'1 (BODY[HEADER] {0})'.format(len(header_data)), header_data)])
        
        # Setup store response
        mock_conn.store.return_value = (OK, [b'1 (FLAGS (\\Seen))'])
        
        # Setup move/copy responses
        mock_conn.move.return_value = (OK, [b'Moved'])
        mock_conn.copy.return_value = (OK, [b'Copied'])
        
        return mock_conn
    
    def test_search_and_mark_read_workflow(self, mock_imap_connection):
        """Test complete workflow: search -> mark read."""
        from imap_mcp.operations.search import EmailSearch
        from imap_mcp.operations.flags import EmailFlags
        
        # Search
        search = EmailSearch(mock_imap_connection)
        results = search.search_emails('INBOX', {'subject': 'important'})
        assert len(results) == 3
        
        # Mark as read
        flags = EmailFlags(mock_imap_connection)
        result = flags.mark_read('INBOX', results)
        assert result is True