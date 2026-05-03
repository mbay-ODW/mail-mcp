"""
IMAP/SMTP MCP Server - MCP Protocol Interface

Provides email management capabilities via the MCP (Model Context Protocol).
Supports stdio (local) and SSE (remote via Traefik + Authelia OIDC) transport.
"""

import asyncio
import logging
import os

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent

from .tools import get_all_tools, handle_imap_tool, handle_smtp_tool

_log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# Create MCP Server
app = Server("mail-mcp")


@app.list_tools()
async def list_tools():
    """List all available tools."""
    return get_all_tools()


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list:
    """Handle tool calls."""
    try:
        result = await handle_imap_tool(name, arguments)
        if result is not None:
            return result
        result = await handle_smtp_tool(name, arguments)
        if result is not None:
            return result
        raise ValueError(f"Unknown tool: {name}")
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


# ---------------------------------------------------------------------------
# SSE Transport with OIDC Introspection (Traefik + Authelia)
# ---------------------------------------------------------------------------


def _start_db_syncer() -> None:
    """Initialise SQLite store and start background sync if EMAIL_DB_ENABLED=true."""
    from .config import DBConfig
    from .db import EmailSyncer, init_email_store

    cfg = DBConfig.from_env()
    if not cfg.enabled:
        return

    store = init_email_store(cfg.path)
    syncer = EmailSyncer(
        store=store,
        sync_interval=cfg.sync_interval,
        sync_days=cfg.sync_days,
    )
    syncer.start()
    logging.info(
        "Email DB enabled: path=%s interval=%ds days=%d",
        cfg.path,
        cfg.sync_interval,
        cfg.sync_days,
    )


def _run_sse() -> None:
    import httpx
    import uvicorn
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.routing import Mount, Route

    _start_db_syncer()

    mcp_api_key = os.getenv("MCP_API_KEY", "")
    oidc_introspection_url = os.getenv("OIDC_INTROSPECTION_URL", "")
    oidc_client_id = os.getenv("OIDC_CLIENT_ID", "")
    oidc_client_secret = os.getenv("OIDC_CLIENT_SECRET", "")

    # Auth result: (ok, reason). reason ∈ {None, "no_header", "invalid_token"}.
    # See _unauthorized() for how each reason is translated to a 401 response.
    async def _is_authorized(request: Request) -> tuple[bool, str | None]:
        if not mcp_api_key:
            return True, None
        auth = request.headers.get("Authorization", "")
        logging.debug(
            "Auth check: has_auth=%s starts_bearer=%s has_introspection_url=%s has_client_id=%s has_client_secret=%s",
            bool(auth),
            auth.startswith("Bearer "),
            bool(oidc_introspection_url),
            bool(oidc_client_id),
            bool(oidc_client_secret),
        )
        if not auth:
            return False, "no_header"
        if auth == f"Bearer {mcp_api_key}":
            logging.info("Auth OK: statischer Bearer Token")
            return True, None
        if not auth.startswith("Bearer "):
            return False, "invalid_token"
        if oidc_introspection_url and oidc_client_id and oidc_client_secret:
            jwt_token = auth[7:]
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        oidc_introspection_url,
                        data={"token": jwt_token},
                        auth=(oidc_client_id, oidc_client_secret),
                        timeout=5.0,
                    )
                    logging.debug(
                        "Introspection HTTP %s body=%s",
                        resp.status_code,
                        resp.text[:500],
                    )
                    data = resp.json()
                    active = data.get("active", False)
                    logging.info("OIDC Introspection: active=%s", active)
                    if active:
                        return True, None
                    return False, "invalid_token"
            except Exception as e:
                logging.error("Introspection fehlgeschlagen: %s", e)
                return False, "invalid_token"
        return False, "invalid_token"

    def _unauthorized(reason: str | None) -> Response:
        """Build a 401 with an RFC 6750 WWW-Authenticate hint so the OAuth
        client knows whether to refresh its token or re-prompt the user."""
        realm = "mail-mcp"
        if reason == "invalid_token":
            www = (
                f'Bearer realm="{realm}", error="invalid_token", '
                f'error_description="The access token expired or is invalid"'
            )
        else:
            www = f'Bearer realm="{realm}"'
        return Response("Unauthorized", status_code=401, headers={"WWW-Authenticate": www})

    sse = SseServerTransport("/messages/")

    async def handle_sse(request: Request):
        ok, reason = await _is_authorized(request)
        if not ok:
            return _unauthorized(reason)
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await app.run(streams[0], streams[1], app.create_initialization_options())
        # Must return Response() – otherwise Starlette calls None() on disconnect
        # and logs "Exception in ASGI application" (MCP SDK ≥ 1.6 requirement)
        return Response()

    # Streamable-HTTP transport (current MCP spec). Modern Claude.ai sends
    # POST requests to the connector URL with real JSON-RPC payloads from
    # the very first connect, regardless of whether the URL ends in /sse
    # or /mcp. We MUST speak Streamable-HTTP there or the connector cannot
    # initialise after a fresh OAuth login (e.g. after an Authelia restart).
    import anyio
    from mcp.server.streamable_http import StreamableHTTPServerTransport

    async def handle_streamable_http(request: Request):
        ok, reason = await _is_authorized(request)
        if not ok:
            logging.warning("Streamable-HTTP denied – unauthenticated (%s) reason=%s", request.url.path, reason)
            return _unauthorized(reason)
        logging.info("Streamable-HTTP request (%s) from %s", request.url.path, request.client)
        # Stateless: new transport per request.
        transport = StreamableHTTPServerTransport(
            mcp_session_id=None, is_json_response_enabled=True
        )
        try:
            async with transport.connect() as streams:
                async with anyio.create_task_group() as tg:

                    async def _run_server():
                        try:
                            await app.run(
                                streams[0],
                                streams[1],
                                app.create_initialization_options(),
                            )
                        except Exception:
                            logging.exception("server.run crashed")

                    tg.start_soon(_run_server)
                    await transport.handle_request(
                        request.scope, request.receive, request._send
                    )
                    tg.cancel_scope.cancel()
        except Exception:
            logging.exception("Streamable-HTTP handler error")
            raise
        return Response()

    starlette_app = Starlette(
        routes=[
            # Streamable-HTTP (current spec) – Claude.ai uses this first.
            Route("/sse", endpoint=handle_streamable_http, methods=["POST"]),
            Route("/mcp", endpoint=handle_streamable_http, methods=["POST"]),
            # Classic SSE (Claude Desktop / older clients).
            Route("/sse", endpoint=handle_sse, methods=["GET"]),
            Mount("/messages/", app=sse.handle_post_message),
        ],
    )

    port = int(os.getenv("PORT", "8000"))
    logging.info("Starting mail-mcp SSE server on port %d", port)
    uvicorn.run(starlette_app, host="0.0.0.0", port=port)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


async def _main_stdio():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def run():
    """Synchronous entry point for console script."""
    if os.getenv("MCP_TRANSPORT", "stdio") == "sse":
        _run_sse()
    else:
        asyncio.run(_main_stdio())


if __name__ == "__main__":
    run()
