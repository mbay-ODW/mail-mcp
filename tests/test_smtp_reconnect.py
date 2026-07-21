"""Regression tests for stale-SMTP-connection recovery.

The mail servers are long-running; the provider drops idle SMTP sessions
after a while. Before the fix, `send.py` handed the cached raw connection
straight to `send_message()`, so every send after that failed with
smtplib's ``please run connect() first`` until the container was restarted.
"""

from __future__ import annotations

import smtplib
from unittest.mock import MagicMock

from mail_mcp.smtp.operations import send as send_mod


class FakeSMTPClient:
    """Minimal stand-in for `SMTPClient` with a killable socket."""

    def __init__(self, *, dead: bool = False):
        self.connect_calls = 0
        self.disconnect_calls = 0
        self._dead = dead
        self._connection = self._make_conn()

    def _make_conn(self):
        conn = MagicMock(name="smtp_conn")
        if self._dead:
            # Mirrors smtplib.SMTP.send() when self.sock is None.
            conn.send_message.side_effect = smtplib.SMTPServerDisconnected(
                "please run connect() first"
            )
        return conn

    # `SMTPClient` exposes exactly these three.
    def _ensure_connected(self):
        return self._connection

    def connect(self):
        self.connect_calls += 1
        self._dead = False
        self._connection = self._make_conn()

    def disconnect(self):
        self.disconnect_calls += 1


def test_send_message_uses_live_connection_when_healthy():
    client = FakeSMTPClient()
    msg = MagicMock()
    send_mod._send_message(client, msg, from_addr="me@x.de", to_addrs=["a@b.de"])

    client._connection.send_message.assert_called_once_with(
        msg, from_addr="me@x.de", to_addrs=["a@b.de"]
    )
    assert client.connect_calls == 0  # no needless reconnect


def test_send_message_recovers_from_stale_connection():
    """The actual bug: cached socket is dead -> reconnect once and retry."""
    client = FakeSMTPClient(dead=True)
    dead_conn = client._connection
    msg = MagicMock()

    send_mod._send_message(client, msg, from_addr="me@x.de", to_addrs=["a@b.de"])

    # The dead connection was tried, then dropped and rebuilt.
    dead_conn.send_message.assert_called_once()
    assert client.disconnect_calls == 1
    assert client.connect_calls == 1
    # The retry went out on the *new* connection and succeeded.
    assert client._connection is not dead_conn
    client._connection.send_message.assert_called_once_with(
        msg, from_addr="me@x.de", to_addrs=["a@b.de"]
    )


def test_get_smtp_client_prefers_ensure_connected():
    """_get_smtp_client must go through the liveness check, not the raw attr."""
    client = FakeSMTPClient()
    client._ensure_connected = MagicMock(return_value="live-conn")
    assert send_mod._get_smtp_client(client) == "live-conn"
    client._ensure_connected.assert_called_once()


def test_send_email_reports_failure_instead_of_raising():
    """A permanently dead SMTP still yields a SendResult, not an exception."""
    client = FakeSMTPClient(dead=True)
    # Reconnect keeps producing a dead socket.
    client.connect = lambda: None

    result = send_mod.send_email(
        client, to=["a@b.de"], subject="Hi", body_text="x", from_addr="me@x.de"
    )
    assert result.success is False
    assert result.error
