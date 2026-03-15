"""Tests for SMTP authentication utilities."""

import pytest

from mail_mcp.smtp.auth import (
    validate_email_address,
    validate_email_address_with_error,
    parse_recipients,
    generate_oauth2_string,
)


class TestValidateEmailAddress:
    """Test cases for email validation."""

    def test_valid_email(self):
        """Test valid email addresses."""
        assert validate_email_address("test@example.com") is True
        assert validate_email_address("user.name@domain.org") is True
        assert validate_email_address("user+tag@example.co.uk") is True

    def test_invalid_email(self):
        """Test invalid email addresses."""
        assert validate_email_address("") is False
        assert validate_email_address("invalid") is False
        assert validate_email_address("no@domain") is False
        assert validate_email_address("@example.com") is False

    def test_validate_with_error_valid(self):
        """Test detailed validation for valid email."""
        is_valid, error = validate_email_address_with_error("test@example.com")
        assert is_valid is True
        assert error == ""

    def test_validate_with_error_empty(self):
        """Test detailed validation for empty email."""
        is_valid, error = validate_email_address_with_error("")
        assert is_valid is False
        assert "空" in error


class TestParseRecipients:
    """Test cases for parsing recipients."""

    def test_single_recipient(self):
        """Test parsing single recipient."""
        valid, invalid = parse_recipients("test@example.com")
        assert valid == ["test@example.com"]
        assert invalid == []

    def test_multiple_recipients_comma(self):
        """Test parsing multiple recipients with comma."""
        valid, invalid = parse_recipients("a@test.com, b@test.com")
        assert len(valid) == 2
        assert "a@test.com" in valid
        assert "b@test.com" in valid

    def test_multiple_recipients_semicolon(self):
        """Test parsing multiple recipients with semicolon."""
        valid, invalid = parse_recipients("a@test.com; b@test.com")
        assert len(valid) == 2

    def test_mixed_valid_invalid(self):
        """Test parsing with mixed valid/invalid addresses."""
        valid, invalid = parse_recipients("valid@test.com, invalid-email")
        assert len(valid) == 1
        assert len(invalid) == 1


class TestGenerateOAuth2String:
    """Test cases for OAuth2 string generation."""

    def test_basic_oauth2_string(self):
        """Test basic OAuth2 string generation."""
        result = generate_oauth2_string("user@example.com", "access_token")
        assert result  # Should return a non-empty base64 string
        assert isinstance(result, str)