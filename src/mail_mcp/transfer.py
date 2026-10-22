"""Direct server-to-server attachment transfer helpers.

Uploads attachment binaries directly to Paperless-ngx or HERO without
passing base64 through Claude's context window.
"""

import logging
from typing import Any

import httpx

from .config import TransferConfig

_cfg: TransferConfig | None = None


def _get_cfg() -> TransferConfig:
    global _cfg
    if _cfg is None:
        _cfg = TransferConfig.from_env()
    return _cfg


async def upload_to_paperless(
    data: bytes,
    filename: str,
    content_type: str,
    title: str | None = None,
    correspondent_id: int | None = None,
    document_type_id: int | None = None,
    tag_ids: list[int] | None = None,
) -> dict[str, Any]:
    """POST attachment directly to Paperless-ngx /api/documents/post_document/.

    Returns the Paperless task UUID (async import) or raises on error.
    """
    cfg = _get_cfg()
    if not cfg.paperless_enabled:
        raise RuntimeError(
            "Paperless transfer not configured – set PAPERLESS_URL and PAPERLESS_API_KEY."
        )

    headers = {"Authorization": f"Token {cfg.paperless_api_key}"}
    files = {"document": (filename, data, content_type)}

    form_data: dict[str, Any] = {}
    if title:
        form_data["title"] = title
    if correspondent_id is not None:
        form_data["correspondent"] = str(correspondent_id)
    if document_type_id is not None:
        form_data["document_type"] = str(document_type_id)
    # Paperless accepts tags as repeated form field
    tag_data = [("tags", str(t)) for t in (tag_ids or [])]

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{cfg.paperless_url}/api/documents/post_document/",
            headers=headers,
            files=files,
            data=form_data if not tag_data else {**form_data},
        )
        if tag_data:
            # httpx doesn't support repeated keys in data= dict; rebuild manually
            resp = await client.post(
                f"{cfg.paperless_url}/api/documents/post_document/",
                headers=headers,
                content=_build_multipart(files, form_data, tag_data),
            )
        resp.raise_for_status()
        # Paperless returns a quoted UUID string on success
        task_id = resp.text.strip().strip('"')
        logging.info("Paperless upload OK: task_id=%s filename=%s", task_id, filename)
        return {
            "success": True,
            "task_id": task_id,
            "filename": filename,
            "size_bytes": len(data),
            "message": (
                f"Document queued for import in Paperless. "
                f"Task ID: {task_id}. "
                f"Check status at {cfg.paperless_url}/api/tasks/?task_id={task_id}"
            ),
        }


def _build_multipart(
    files: dict,
    form_data: dict,
    extra_pairs: list[tuple[str, str]],
) -> bytes:
    """Build a raw multipart/form-data body with repeated field names."""
    import uuid

    boundary = uuid.uuid4().hex
    parts: list[bytes] = []

    for key, value in form_data.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
        )

    for key, value in extra_pairs:
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
        )

    for key, (fname, data, ctype) in files.items():
        header = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{key}"; filename="{fname}"\r\n'
            f"Content-Type: {ctype}\r\n\r\n"
        ).encode()
        parts.append(header + data + b"\r\n")

    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts)


async def upload_to_hero(
    data: bytes,
    filename: str,
    content_type: str,
    project_id: str,
    category: str | None = None,  # kept for backwards compat; unused
    document_type_id: int = 551120,  # 551120 = "Allgemein" (base_type generic)
) -> dict[str, Any]:
    """Upload attachment to a HERO project_match using HERO's two-step flow.

    Step 1: POST the binary as multipart/form-data to
            /app/v8/FileUploads/upload (auth via `x-auth-token` header,
            NOT `Authorization: Bearer`!) → response contains 'uuid'.
    Step 2: Run the GraphQL upload_document mutation with file_upload_uuid +
            target=project_match + target_id=projectId (auth via Bearer
            here, since this hits /api/external/v7/graphql).

    The single-shot graphql-multipart-request-spec upload that this used to
    do is NOT supported by HERO's API. Confirmed by HERO support
    2026-05-06; see https://support.hero-software.de/hc/s/article/
    7474773464732-GraphQL-Dateiupload.
    """
    del category  # legacy parameter, ignored
    cfg = _get_cfg()
    if not cfg.hero_enabled:
        raise RuntimeError("HERO transfer not configured – set HERO_API_KEY.")

    # ---- Step 1: REST file upload --------------------------------------------------
    # Different auth header than GraphQL: `x-auth-token` instead of Bearer.
    upload_headers = {
        "x-auth-token": cfg.hero_api_key,
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            cfg.hero_file_upload_url,
            files={"file": (filename, data, content_type)},
            headers=upload_headers,
        )
        resp.raise_for_status()
        upload_resp = resp.json()
    # HERO antwortet {"status": "success", "data": {"uuid": ...}} – die uuid
    # liegt unter data.uuid, NICHT auf Top-Level. Fallback auf Top-Level.
    uuid = (upload_resp.get("data") or {}).get("uuid") or upload_resp.get("uuid")
    if not uuid:
        raise RuntimeError(f"HERO file-uploads response missing 'uuid' field: {upload_resp}")
    logging.info(
        "HERO step 1 OK: filename=%s size=%d uuid=%s",
        filename,
        len(data),
        uuid,
    )

    # ---- Step 2: GraphQL upload_document mutation ----------------------------------
    try:
        project_id_int = int(project_id)
    except (TypeError, ValueError) as e:
        raise RuntimeError(
            f"project_id must be numeric (project_match.id), got: {project_id!r}"
        ) from e

    # upload_document verlangt ein document_type_id (sonst 422
    # "document_type_id: Dieses Feld ist erforderlich"). Default 551120 =
    # "Allgemein" (base_type generic).
    mutation = """
    mutation UploadDocument($uuid: String!, $projectId: Int!, $docTypeId: Int!) {
      upload_document(
        document: {
          project_match_id: $projectId
          type: "file_upload"
          document_type_id: $docTypeId
        }
        file_upload_uuid: $uuid
        target: project_match
        target_id: $projectId
      ) {
        id
        nr
        type
      }
    }
    """
    payload = {
        "query": mutation,
        "variables": {
            "uuid": uuid,
            "projectId": project_id_int,
            "docTypeId": int(document_type_id),
        },
    }
    # GraphQL endpoint uses Bearer auth (different from upload above).
    graphql_headers = {
        "Authorization": f"Bearer {cfg.hero_api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            cfg.hero_graphql_url,
            json=payload,
            headers=graphql_headers,
        )
        resp.raise_for_status()
        resp_data = resp.json()
    if "errors" in resp_data:
        raise RuntimeError(f"HERO GraphQL error: {resp_data['errors']}")
    result = (resp_data.get("data") or {}).get("upload_document") or {}
    logging.info(
        "HERO step 2 OK: filename=%s project_match_id=%d document_id=%s",
        filename,
        project_id_int,
        result.get("id"),
    )
    return {
        "success": True,
        "filename": filename,
        "size_bytes": len(data),
        "uuid": uuid,
        "document": result,
    }


async def download_from_paperless(
    doc_id: int,
    as_original: bool = False,
) -> dict[str, Any]:
    """Fetch a document binary from Paperless-ngx server-to-server.

    Returns a dict shaped ``{"filename", "content_type", "data"}`` (raw bytes,
    not base64) suitable for direct attachment to an outgoing email. The
    bytes never traverse Claude's context window.

    Args:
        doc_id: Paperless document primary key.
        as_original: If True, fetch the originally uploaded file (e.g. the
            raw PDF/scan as ingested). If False (default), fetch the archive
            version – Paperless's post-OCR PDF, which is usually what you
            want for re-sending because it's been normalized.

    Raises:
        RuntimeError: Paperless not configured.
        httpx.HTTPStatusError: Paperless responded with a non-2xx status.
    """
    cfg = _get_cfg()
    if not cfg.paperless_enabled:
        raise RuntimeError(
            "Paperless transfer not configured – set PAPERLESS_URL and PAPERLESS_API_KEY."
        )

    headers = {"Authorization": f"Token {cfg.paperless_api_key}"}
    suffix = "?original=true" if as_original else ""
    download_url = f"{cfg.paperless_url}/api/documents/{doc_id}/download/{suffix}"
    meta_url = f"{cfg.paperless_url}/api/documents/{doc_id}/"

    async with httpx.AsyncClient(timeout=60) as client:
        # Fetch metadata (filename + mime) in parallel-ish – cheap GETs.
        meta_resp = await client.get(meta_url, headers=headers)
        meta_resp.raise_for_status()
        meta = meta_resp.json()

        data_resp = await client.get(download_url, headers=headers)
        data_resp.raise_for_status()

    # Filename precedence:
    #   1. Content-Disposition (authoritative – set by Paperless to the
    #      filename the recipient should see).
    #   2. original_file_name from the JSON.
    #   3. Synthetic fallback "paperless-<id>.pdf".
    filename = _filename_from_disposition(data_resp.headers.get("content-disposition"))
    if not filename:
        filename = meta.get("original_file_name") or f"paperless-{doc_id}.pdf"

    content_type = (
        data_resp.headers.get("content-type", "").split(";")[0].strip()
        or meta.get("mime_type")
        or "application/pdf"
    )
    data = data_resp.content

    logging.info(
        "Paperless download OK: doc_id=%s filename=%s size=%d original=%s",
        doc_id,
        filename,
        len(data),
        as_original,
    )
    return {"filename": filename, "content_type": content_type, "data": data}


def _filename_from_disposition(header: str | None) -> str | None:
    """Extract filename from a Content-Disposition header.

    Handles both the plain ``filename="x"`` and RFC 5987 ``filename*=UTF-8''x``
    forms. Returns ``None`` if neither is present or parsable.
    """
    if not header:
        return None
    import re
    from urllib.parse import unquote

    # RFC 5987 first – it's the more accurate form when present.
    m = re.search(r"filename\*\s*=\s*[^']*''([^;]+)", header, re.IGNORECASE)
    if m:
        return unquote(m.group(1).strip().strip('"'))
    m = re.search(r'filename\s*=\s*"?([^";]+)"?', header, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


class _Budget:
    """Shared byte budget for all attach_from downloads of one call."""

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        self.used = 0

    def take(self, n: int, what: str) -> None:
        self.used += n
        if self.used > self.max_bytes:
            raise ValueError(
                f"attach_from: Größenlimit {self.max_bytes // (1024 * 1024)} MB überschritten "
                f"(bei {what}). Weniger oder kleinere Dateien anhängen."
            )


async def _stream_download(
    client: httpx.AsyncClient, url: str, budget: _Budget, what: str, **kwargs: Any
) -> tuple[bytes, httpx.Headers]:
    """GET ``url`` in chunks, aborting as soon as the budget is exceeded."""
    chunks: list[bytes] = []
    async with client.stream("GET", url, **kwargs) as resp:
        if resp.status_code == 404:
            raise FileNotFoundError(f"attach_from: {what} nicht gefunden (404)")
        resp.raise_for_status()
        async for chunk in resp.aiter_bytes():
            budget.take(len(chunk), what)
            chunks.append(chunk)
        return b"".join(chunks), resp.headers


def _guess_type(filename: str, header_type: str | None = None) -> str:
    import mimetypes

    guessed, _ = mimetypes.guess_type(filename)
    if guessed:
        return guessed
    header_type = (header_type or "").split(";")[0].strip()
    return header_type or "application/octet-stream"


async def download_from_nextcloud(path: str, budget: _Budget) -> dict[str, Any]:
    """Fetch a file from Nextcloud via WebDAV with the instance's credentials."""
    from urllib.parse import quote

    cfg = _get_cfg()
    if not cfg.nextcloud_enabled:
        raise RuntimeError(
            "Nextcloud nicht konfiguriert – NEXTCLOUD_URL, NEXTCLOUD_USER und "
            "NEXTCLOUD_PASSWORD setzen."
        )
    clean = path.strip().lstrip("/")
    if not clean or any(seg == ".." for seg in clean.split("/")):
        raise ValueError(f"attach_from[nextcloud]: ungültiger Pfad {path!r}")
    url = (
        f"{cfg.nextcloud_url}/remote.php/dav/files/{quote(cfg.nextcloud_user, safe='')}/"
        f"{quote(clean)}"
    )
    async with httpx.AsyncClient(timeout=120) as client:
        data, headers = await _stream_download(
            client,
            url,
            budget,
            f"Nextcloud-Datei {clean!r}",
            auth=(cfg.nextcloud_user, cfg.nextcloud_password),
        )
    filename = clean.rsplit("/", 1)[-1]
    return {
        "filename": filename,
        "content_type": _guess_type(filename, headers.get("content-type")),
        "data": data,
    }


def _check_public_https(url: str) -> str:
    """Allow only https URLs whose host resolves to public addresses.

    The fetched bytes leave the house as an attachment, so internal
    services must not be reachable through this path.
    """
    import ipaddress
    import socket
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError("attach_from[url]: nur https-URLs sind erlaubt")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or 443)
    except socket.gaierror as exc:
        raise ValueError(f"attach_from[url]: Host {parts.hostname!r} unbekannt") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise ValueError(f"attach_from[url]: {parts.hostname!r} zeigt auf eine interne Adresse")
    return parts.path


async def download_from_url(url: str, budget: _Budget) -> dict[str, Any]:
    from urllib.parse import unquote

    path = _check_public_https(url)
    # Redirects are not followed: each hop would need the same host check.
    async with httpx.AsyncClient(timeout=120, follow_redirects=False) as client:
        data, headers = await _stream_download(client, url, budget, f"URL {url}")
    filename = _filename_from_disposition(headers.get("content-disposition"))
    if not filename:
        filename = unquote(path.rstrip("/").rsplit("/", 1)[-1]) or "download"
    return {
        "filename": filename,
        "content_type": _guess_type(filename, headers.get("content-type")),
        "data": data,
    }


async def resolve_attach_from(
    items: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Resolve ``attach_from`` references into base64 attachment dicts.

    Input shape (per item)::

        {"source": "paperless", "id": 1234, "filename": "optional", "as_original": false}
        {"source": "nextcloud", "path": "Projekte/x/FUE.pdf", "filename": "optional"}
        {"source": "url", "url": "https://…", "filename": "optional"}

    Output shape (per item, matches existing ``attachments`` schema)::

        {"filename": "...", "content_type": "...", "data_base64": "..."}

    Bytes are downloaded directly from the source and never round-trip
    through Claude's context. All downloads of one call share one size
    budget (``ATTACH_FROM_MAX_MB``). Returns an empty list if ``items`` is
    None/empty so callers can blindly extend their attachments list.
    """
    if not items:
        return []

    import base64 as _b64

    budget = _Budget(_get_cfg().attach_from_max_mb * 1024 * 1024)
    resolved: list[dict[str, Any]] = []
    for entry in items:
        source = (entry.get("source") or "").lower()
        if source == "paperless":
            doc_id_raw = entry.get("id")
            if doc_id_raw is None:
                raise ValueError("attach_from[paperless]: 'id' is required")
            try:
                doc_id = int(doc_id_raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"attach_from[paperless]: 'id' must be numeric, got {doc_id_raw!r}"
                ) from exc
            doc = await download_from_paperless(
                doc_id=doc_id,
                as_original=bool(entry.get("as_original", False)),
            )
            budget.take(len(doc["data"]), f"Paperless-Dokument {doc_id}")
        elif source == "nextcloud":
            if not entry.get("path"):
                raise ValueError("attach_from[nextcloud]: 'path' is required")
            doc = await download_from_nextcloud(entry["path"], budget)
        elif source == "url":
            if not entry.get("url"):
                raise ValueError("attach_from[url]: 'url' is required")
            doc = await download_from_url(entry["url"], budget)
        elif source == "hero":
            # HERO does not currently expose a documented document-download
            # endpoint via GraphQL or REST. Once HERO support confirms the
            # right endpoint (see support email thread 2026-05-06) we can
            # add a `download_from_hero` counterpart here. Until then this
            # raises so the caller gets a clear, non-silent failure.
            raise NotImplementedError(
                "attach_from[hero]: server-side download from HERO is not yet "
                "supported. Open a ticket with HERO support to confirm the "
                "document-download endpoint, then extend transfer.py."
            )
        else:
            raise ValueError(
                f"attach_from: unknown source {source!r}. "
                "Supported: 'paperless', 'nextcloud', 'url'."
            )
        resolved.append(
            {
                "filename": entry.get("filename") or doc["filename"],
                "content_type": doc["content_type"],
                "data_base64": _b64.b64encode(doc["data"]).decode("ascii"),
            }
        )
    return resolved


__all__ = [
    "upload_to_paperless",
    "upload_to_hero",
    "download_from_paperless",
    "download_from_nextcloud",
    "download_from_url",
    "resolve_attach_from",
]
