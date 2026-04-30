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


def _run_sse() -> None:
    import httpx
    import uvicorn
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.routing import Mount, Route

    mcp_api_key = os.getenv("MCP_API_KEY", "")
    oidc_introspection_url = os.getenv("OIDC_INTROSPECTION_URL", "")
    oidc_client_id = os.getenv("OIDC_CLIENT_ID", "")
    oidc_client_secret = os.getenv("OIDC_CLIENT_SECRET", "")

    async def _is_authorized(request: Request) -> bool:
        if not mcp_api_key:
            return True
        auth = request.headers.get("Authorization", "")
        logging.info(
            "Auth check: has_auth=%s starts_bearer=%s has_introspection_url=%s has_client_id=%s has_client_secret=%s",
            bool(auth),
            auth.startswith("Bearer "),
            bool(oidc_introspection_url),
            bool(oidc_client_id),
            bool(oidc_client_secret),
        )
        if auth == f"Bearer {mcp_api_key}":
            logging.info("Auth OK: statischer Bearer Token")
            return True
        if (
            auth.startswith("Bearer ")
            and oidc_introspection_url
            and oidc_client_id
            and oidc_client_secret
        ):
            jwt_token = auth[7:]
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        oidc_introspection_url,
                        data={"token": jwt_token},
                        auth=(oidc_client_id, oidc_client_secret),
                        timeout=5.0,
                    )
                    logging.info(
                        "Introspection HTTP %s body=%s",
                        resp.status_code,
                        resp.text[:500],
                    )
                    data = resp.json()
                    active = data.get("active", False)
                    logging.info("OIDC Introspection: active=%s", active)
                    return active
            except Exception as e:
                logging.error("Introspection fehlgeschlagen: %s", e)
        return False

    sse = SseServerTransport("/messages/")

    async def handle_sse(request: Request):
        if not await _is_authorized(request):
            return Response("Unauthorized", status_code=401)
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await app.run(streams[0], streams[1], app.create_initialization_options())

    starlette_app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
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
