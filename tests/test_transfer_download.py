"""Tests for the server-side download helpers in ``transfer.py``.

Covers:

* ``download_from_paperless`` – correct URL, auth, filename precedence
  (Content-Disposition > original_file_name > synthetic).
* ``resolve_attach_from`` – Paperless source → base64 dict shape;
  unknown source / HERO source raise; empty input returns ``[]``.
"""

from __future__ import annotations

import base64
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mail_mcp import transfer


@pytest.fixture(autouse=True)
def _reset_transfer_cfg(monkeypatch):
    """Force a fresh TransferConfig per test so env vars take effect."""
    monkeypatch.setattr(transfer, "_cfg", None)
    monkeypatch.setenv("PAPERLESS_URL", "http://paperless.test:8000")
    monkeypatch.setenv("PAPERLESS_API_KEY", "test-token")
    yield


def _mock_async_client(responses: dict[str, Any]) -> MagicMock:
    """Build a MagicMock that acts as an ``httpx.AsyncClient`` factory.

    ``responses`` maps URL → mock response object; we drive ``.get`` to
    return whichever response matches the request URL.
    """
    client = MagicMock()

    async def _get(url, headers=None):
        if url not in responses:
            raise AssertionError(f"Unexpected URL: {url}")
        return responses[url]

    client.get = AsyncMock(side_effect=_get)

    async_ctx = MagicMock()
    async_ctx.__aenter__ = AsyncMock(return_value=client)
    async_ctx.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock(return_value=async_ctx)
    return factory


def _resp(*, status=200, content=b"", headers=None, json_data=None):
    r = MagicMock()
    r.status_code = status
    r.content = content
    r.headers = headers or {}
    if json_data is not None:
        r.json = MagicMock(return_value=json_data)
    r.raise_for_status = MagicMock()
    return r


@pytest.mark.asyncio
async def test_download_from_paperless_uses_content_disposition(monkeypatch):
    meta_url = "http://paperless.test:8000/api/documents/42/"
    download_url = "http://paperless.test:8000/api/documents/42/download/"

    pdf_bytes = b"%PDF-1.4 fake bytes"
    factory = _mock_async_client(
        {
            meta_url: _resp(
                json_data={
                    "id": 42,
                    "original_file_name": "scan.pdf",
                    "mime_type": "application/pdf",
                }
            ),
            download_url: _resp(
                content=pdf_bytes,
                headers={
                    "content-disposition": 'attachment; filename="invoice-2026-01.pdf"',
                    "content-type": "application/pdf",
                },
            ),
        }
    )
    monkeypatch.setattr(transfer.httpx, "AsyncClient", factory)

    doc = await transfer.download_from_paperless(42)

    assert doc["filename"] == "invoice-2026-01.pdf"
    assert doc["content_type"] == "application/pdf"
    assert doc["data"] == pdf_bytes


@pytest.mark.asyncio
async def test_download_from_paperless_falls_back_to_original_filename(monkeypatch):
    """When Content-Disposition is missing, use the API's original_file_name."""
    meta_url = "http://paperless.test:8000/api/documents/7/"
    download_url = "http://paperless.test:8000/api/documents/7/download/?original=true"

    factory = _mock_async_client(
        {
            meta_url: _resp(
                json_data={
                    "id": 7,
                    "original_file_name": "rechnung.pdf",
                    "mime_type": "application/pdf",
                }
            ),
            download_url: _resp(
                content=b"bytes",
                headers={"content-type": "application/pdf"},
            ),
        }
    )
    monkeypatch.setattr(transfer.httpx, "AsyncClient", factory)

    doc = await transfer.download_from_paperless(7, as_original=True)

    assert doc["filename"] == "rechnung.pdf"


@pytest.mark.asyncio
async def test_download_from_paperless_synthetic_fallback(monkeypatch):
    meta_url = "http://paperless.test:8000/api/documents/99/"
    download_url = "http://paperless.test:8000/api/documents/99/download/"

    factory = _mock_async_client(
        {
            meta_url: _resp(json_data={"id": 99}),
            download_url: _resp(content=b"x", headers={"content-type": ""}),
        }
    )
    monkeypatch.setattr(transfer.httpx, "AsyncClient", factory)

    doc = await transfer.download_from_paperless(99)

    assert doc["filename"] == "paperless-99.pdf"
    assert doc["content_type"] == "application/pdf"


@pytest.mark.asyncio
async def test_download_from_paperless_raises_when_not_configured(monkeypatch):
    monkeypatch.setattr(transfer, "_cfg", None)
    monkeypatch.delenv("PAPERLESS_URL", raising=False)
    monkeypatch.delenv("PAPERLESS_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="Paperless transfer not configured"):
        await transfer.download_from_paperless(1)


@pytest.mark.asyncio
async def test_resolve_attach_from_empty_returns_empty():
    assert await transfer.resolve_attach_from(None) == []
    assert await transfer.resolve_attach_from([]) == []


@pytest.mark.asyncio
async def test_resolve_attach_from_paperless_returns_b64_dict(monkeypatch):
    """resolve_attach_from should call download_from_paperless and base64-encode."""
    fake_bytes = b"hello-world"

    async def fake_download(doc_id, as_original=False):
        assert doc_id == 1234
        assert as_original is False
        return {
            "filename": "doc.pdf",
            "content_type": "application/pdf",
            "data": fake_bytes,
        }

    monkeypatch.setattr(transfer, "download_from_paperless", fake_download)

    result = await transfer.resolve_attach_from([{"source": "paperless", "id": 1234}])

    assert len(result) == 1
    item = result[0]
    assert item["filename"] == "doc.pdf"
    assert item["content_type"] == "application/pdf"
    assert base64.b64decode(item["data_base64"]) == fake_bytes


@pytest.mark.asyncio
async def test_resolve_attach_from_filename_override(monkeypatch):
    async def fake_download(doc_id, as_original=False):
        return {"filename": "src.pdf", "content_type": "application/pdf", "data": b"x"}

    monkeypatch.setattr(transfer, "download_from_paperless", fake_download)

    result = await transfer.resolve_attach_from(
        [{"source": "paperless", "id": 1, "filename": "renamed.pdf"}]
    )

    assert result[0]["filename"] == "renamed.pdf"


@pytest.mark.asyncio
async def test_resolve_attach_from_missing_id_raises():
    with pytest.raises(ValueError, match="'id' is required"):
        await transfer.resolve_attach_from([{"source": "paperless"}])


@pytest.mark.asyncio
async def test_resolve_attach_from_non_numeric_id_raises():
    with pytest.raises(ValueError, match="must be numeric"):
        await transfer.resolve_attach_from([{"source": "paperless", "id": "not-a-number"}])


@pytest.mark.asyncio
async def test_resolve_attach_from_hero_not_implemented():
    with pytest.raises(NotImplementedError, match="HERO"):
        await transfer.resolve_attach_from([{"source": "hero", "id": 1}])


@pytest.mark.asyncio
async def test_resolve_attach_from_unknown_source_raises():
    with pytest.raises(ValueError, match="unknown source"):
        await transfer.resolve_attach_from([{"source": "dropbox", "id": 1}])


def test_filename_from_disposition_rfc5987():
    h = "attachment; filename*=UTF-8''r%C3%A4chnung.pdf"
    assert transfer._filename_from_disposition(h) == "rächnung.pdf"


def test_filename_from_disposition_plain():
    assert transfer._filename_from_disposition('attachment; filename="x.pdf"') == "x.pdf"


def test_filename_from_disposition_none():
    assert transfer._filename_from_disposition(None) is None
    assert transfer._filename_from_disposition("inline") is None
