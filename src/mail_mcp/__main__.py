#!/usr/bin/env python3
"""
IMAP MCP Server Entry Point

Usage:
    python -m mail_mcp

Environment Variables:
    IMAP_HOST - IMAP server host
    IMAP_PORT - IMAP server port (default: 993)
    EMAIL_USER - Email username
    EMAIL_PASSWORD - Email password
"""

import asyncio
import os
import sys

# 添加 src 到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import jsonschema
from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)

from .server import IMAPClient, IMAPConfig

config = IMAPConfig.from_env()
client = IMAPClient(config)


def _tools() -> list[Tool]:
    """列出所有可用工具"""
    return [
        Tool(
            name="list_folders",
            description="列出所有邮箱文件夹",
            input_schema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="search_emails",
            description="搜索邮件。支持条件: unseen(未读), seen(已读), flagged(星标), from(发件人), subject(主题)",
            input_schema={
                "type": "object",
                "properties": {
                    "folder": {"type": "string", "default": "INBOX", "description": "邮箱文件夹"},
                    "conditions": {
                        "type": "object",
                        "description": "搜索条件，如 {'unseen': true, 'from': 'xxx@xx.com'}",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="mark_read",
            description="标记邮件为已读",
            input_schema={
                "type": "object",
                "properties": {
                    "folder": {"type": "string", "default": "INBOX"},
                    "uid": {"type": "integer", "description": "邮件 UID"},
                },
                "required": ["uid"],
            },
        ),
        Tool(
            name="mark_unread",
            description="标记邮件为未读",
            input_schema={
                "type": "object",
                "properties": {
                    "folder": {"type": "string", "default": "INBOX"},
                    "uid": {"type": "integer", "description": "邮件 UID"},
                },
                "required": ["uid"],
            },
        ),
        Tool(
            name="mark_flagged",
            description="添加星标",
            input_schema={
                "type": "object",
                "properties": {
                    "folder": {"type": "string", "default": "INBOX"},
                    "uid": {"type": "integer", "description": "邮件 UID"},
                },
                "required": ["uid"],
            },
        ),
        Tool(
            name="unmark_flagged",
            description="移除星标",
            input_schema={
                "type": "object",
                "properties": {
                    "folder": {"type": "string", "default": "INBOX"},
                    "uid": {"type": "integer", "description": "邮件 UID"},
                },
                "required": ["uid"],
            },
        ),
        Tool(
            name="move_email",
            description="移动邮件到其他文件夹",
            input_schema={
                "type": "object",
                "properties": {
                    "folder": {"type": "string", "default": "INBOX"},
                    "uid": {"type": "integer", "description": "邮件 UID"},
                    "destination": {"type": "string", "description": "目标文件夹"},
                },
                "required": ["uid", "destination"],
            },
        ),
        Tool(
            name="delete_email",
            description="删除邮件（移到 Trash）",
            input_schema={
                "type": "object",
                "properties": {
                    "folder": {"type": "string", "default": "INBOX"},
                    "uid": {"type": "integer", "description": "邮件 UID"},
                },
                "required": ["uid"],
            },
        ),
        Tool(
            name="get_email",
            description="获取邮件详情",
            input_schema={
                "type": "object",
                "properties": {
                    "folder": {"type": "string", "default": "INBOX"},
                    "uid": {"type": "integer", "description": "邮件 UID"},
                },
                "required": ["uid"],
            },
        ),
    ]


async def list_tools(
    ctx: ServerRequestContext, params: PaginatedRequestParams | None
) -> ListToolsResult:
    return ListToolsResult(tools=_tools())


async def _dispatch_tool(name: str, arguments: dict) -> list[TextContent]:
    """执行工具调用"""
    try:
        client.connect()

        if name == "list_folders":
            result = client.list_folders()

        elif name == "search_emails":
            folder = arguments.get("folder", "INBOX")
            conditions = arguments.get("conditions", {})
            result = client.search_emails(folder, conditions=conditions)

        elif name == "mark_read":
            folder = arguments.get("folder", "INBOX")
            uid = arguments["uid"]
            result = client.mark_read(folder, uid)

        elif name == "mark_unread":
            folder = arguments.get("folder", "INBOX")
            uid = arguments["uid"]
            result = client.mark_unread(folder, uid)

        elif name == "mark_flagged":
            folder = arguments.get("folder", "INBOX")
            uid = arguments["uid"]
            result = client.mark_flagged(folder, uid)

        elif name == "unmark_flagged":
            folder = arguments.get("folder", "INBOX")
            uid = arguments["uid"]
            result = client.unmark_flagged(folder, uid)

        elif name == "move_email":
            folder = arguments.get("folder", "INBOX")
            uid = arguments["uid"]
            destination = arguments["destination"]
            result = client.move_email(folder, uid, destination)

        elif name == "delete_email":
            folder = arguments.get("folder", "INBOX")
            uid = arguments["uid"]
            result = client.delete_email(folder, uid)

        elif name == "get_email":
            folder = arguments.get("folder", "INBOX")
            uid = arguments["uid"]
            result = client.get_email(folder, uid)

        else:
            result = {"error": f"Unknown tool: {name}"}

        client.disconnect()

        import json

        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


def _error_result(text: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)], is_error=True)


async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
    """mcp 2.x no longer validates arguments, so that happens here."""
    arguments = params.arguments or {}
    tool = next((t for t in _tools() if t.name == params.name), None)
    if tool is not None:
        try:
            jsonschema.validate(arguments, tool.input_schema)
        except jsonschema.ValidationError as e:
            return _error_result(f"Input validation error: {e.message}")
    return CallToolResult(content=await _dispatch_tool(params.name, arguments), is_error=False)


# 创建 MCP 服务器
server = Server("mail-mcp-server", on_list_tools=list_tools, on_call_tool=call_tool)


async def main():
    """启动 MCP 服务器"""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
