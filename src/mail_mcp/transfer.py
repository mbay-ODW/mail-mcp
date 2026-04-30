"""Direct server-to-server attachment transfer helpers.

Uploads attachment binaries directly to Paperless-ngx or HERO without
passing base64 through Claude's context window.
"""

import json
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
    category: str | None = None,
) -> dict[str, Any]:
    """Upload attachment directly to HERO project documents via GraphQL multipart."""
    cfg = _get_cfg()
    if not cfg.hero_enabled:
        raise RuntimeError("HERO transfer not configured – set HERO_API_KEY.")

    headers = {
        "Authorization": f"Bearer {cfg.hero_api_key}",
        "Accept": "application/json",
    }

    query = """
    mutation UploadDocument($project_id: ID!, $file: Upload!, $category: String) {
      upload_document(project_id: $project_id, file: $file, category: $category) {
        id
        filename
        created_at
      }
    }
    """
    variables: dict[str, Any] = {
        "project_id": project_id,
        "file": None,  # replaced by multipart map
        "category": category,
    }
    operations = json.dumps({"query": query, "variables": variables})
    map_ = json.dumps({"0": ["variables.file"]})

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            cfg.hero_graphql_url,
            data={"operations": operations, "map": map_},
            files={"0": (filename, data, content_type)},
            headers=headers,
        )
        resp.raise_for_status()
        resp_data = resp.json()
        if "errors" in resp_data:
            raise RuntimeError(f"HERO GraphQL error: {resp_data['errors']}")
        result = resp_data.get("data", {})
        logging.info("HERO upload OK: filename=%s project=%s", filename, project_id)
        return {"success": True, "filename": filename, "size_bytes": len(data), **result}


__all__ = ["upload_to_paperless", "upload_to_hero"]
