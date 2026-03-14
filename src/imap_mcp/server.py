"""
IMAP MCP Server - MCP Protocol Interface

Provides email management capabilities via the MCP (Model Context Protocol).
"""

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent

from .tools import get_all_tools, handle_imap_tool, handle_smtp_tool


# Create MCP Server
app = Server("mail-mcp-server")


@app.list_tools()
async def list_tools():
    """List all available tools."""
    return get_all_tools()


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list:
    """Handle tool calls."""
    try:
        # Try IMAP tools first
        result = await handle_imap_tool(name, arguments)
        if result is not None:
            return result

        # Try SMTP tools
        result = await handle_smtp_tool(name, arguments)
        if result is not None:
            return result

        raise ValueError(f"Unknown tool: {name}")

    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def main():
    """Main entry point for the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )


def run():
    """Synchronous entry point for console script."""
    import asyncio
    asyncio.run(main())


if __name__ == "__main__":
    run()