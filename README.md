# Mail MCP Server

Email management via MCP (Model Context Protocol). Provides complete IMAP email operations and SMTP sending capabilities through a standardized MCP interface.

## Features

- **Folder Management**: List, create, delete, rename email folders
- **Email Search**: Search with complex IMAP criteria (FROM, TO, SUBJECT, UNSEEN, etc.)
- **Email Operations**: Get full email details including body and attachments
- **Mark Operations**: Mark as read/unread, flagged/unflagged
- **Move/Copy**: Move or copy emails between folders
- **Delete**: Delete emails with expunge
- **SMTP Sending**: Send emails with attachments, replies, and forwards
  - SSL (465) and STARTTLS (587) support
  - Plain text / HTML dual format
  - File attachments
  - OAuth2 authentication (for Gmail, etc.)

## Installation

```bash
# Clone and install
cd imap-mcp-server
pip install -e .

# Or install directly
pip install mcp>=1.0.0 pydantic>=2.0.0 python-dotenv>=1.0.0
```

## Configuration

Configure via environment variables:

### IMAP Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `IMAP_HOST` | IMAP server hostname | `imap.example.com` |
| `IMAP_PORT` | IMAP server port | `993` |
| `EMAIL_USER` | Email username | - |
| `EMAIL_PASSWORD` | Email password | - |
| `IMAP_SSL` | Use SSL connection | `true` |

### SMTP Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `SMTP_HOST` | SMTP server hostname | `smtp.example.com` |
| `SMTP_PORT` | SMTP server port | `465` |
| `EMAIL_USER` | Email username (same as IMAP) | - |
| `EMAIL_PASSWORD` | Email password (same as IMAP) | - |
| `SMTP_SSL` | Use SSL/TLS (port 465) | `true` |
| `SMTP_STARTTLS` | Use STARTTLS (port 587) | `false` |

### Example

```bash
# IMAP (阿里云企业邮箱示例)
export IMAP_HOST=mail.qiye.aliyun.com
export IMAP_PORT=993
export EMAIL_USER=your.email@company.com
export EMAIL_PASSWORD=your-password
export IMAP_SSL=true

# SMTP (for sending)
export SMTP_HOST=smtp.qiye.aliyun.com
export SMTP_PORT=465
export SMTP_SSL=true

# Gmail 示例 (需要 App Password)
# export IMAP_HOST=imap.gmail.com
# export SMTP_HOST=smtp.gmail.com
# export EMAIL_PASSWORD=your-app-password
```

> **Note**: For Gmail, you need to use an [App Password](https://support.google.com/accounts/answer/185833).

## Usage

### As MCP Server

```bash
# Run as stdio MCP server
python -m imap_mcp.server
```

### With npx (npm)

```bash
# Install and run
npx imap-mcp-server
```

## MCP Tools

### Folder Management

#### `list_folders`
List all email folders.

```json
{
  "name": "list_folders",
  "arguments": {}
}
```

#### `create_folder`
Create a new folder.

```json
{
  "name": "create_folder",
  "arguments": {
    "folder_name": "Work/Projects"
  }
}
```

#### `delete_folder`
Delete a folder.

```json
{
  "name": "delete_folder",
  "arguments": {
    "folder_name": "Work/Old"
  }
}
```

#### `rename_folder`
Rename a folder.

```json
{
  "name": "rename_folder",
  "arguments": {
    "old_name": "Work/Old",
    "new_name": "Work/Archive"
  }
}
```

### Email Operations

#### `search_emails`
Search emails with IMAP criteria.

```json
{
  "name": "search_emails",
  "arguments": {
    "folder": "INBOX",
    "criteria": "UNSEEN FROM sender@example.com",
    "limit": 10
  }
}
```

**Common Criteria:**
- `ALL` - All messages
- `UNSEEN` - Unread messages
- `SEEN` - Read messages
- `FLAGGED` - Flagged messages
- `FROM <email>` - From specific sender
- `TO <email>` - To specific recipient
- `SUBJECT <text>` - Subject contains text
- `SINCE <date>` - After date (e.g., "14-Mar-2024")
- `BEFORE <date>` - Before date

#### `get_email`
Get detailed email information.

```json
{
  "name": "get_email",
  "arguments": {
    "folder": "INBOX",
    "message_id": "1",
    "uid": "100",
    "include_body": true
  }
}
```

**Note:** Provide either `message_id` or `uid`.

### Mark Operations

#### `mark_read`
Mark email as read (seen).

```json
{
  "name": "mark_read",
  "arguments": {
    "folder": "INBOX",
    "message_id": "1"
  }
}
```

#### `mark_unread`
Mark email as unread.

```json
{
  "name": "mark_unread",
  "arguments": {
    "folder": "INBOX",
    "uid": "100"
  }
}
```

#### `mark_flagged`
Mark email as flagged (starred).

```json
{
  "name": "mark_flagged",
  "arguments": {
    "folder": "INBOX",
    "message_id": "1"
  }
}
```

#### `unmark_flagged`
Remove flagged status.

```json
{
  "name": "unmark_flagged",
  "arguments": {
    "folder": "INBOX",
    "message_id": "1"
  }
}
```

### Move/Copy Operations

#### `move_email`
Move email to another folder.

```json
{
  "name": "move_email",
  "arguments": {
    "source_folder": "INBOX",
    "target_folder": "Archive",
    "message_id": "1"
  }
}
```

#### `copy_email`
Copy email to another folder.

```json
{
  "name": "copy_email",
  "arguments": {
    "source_folder": "INBOX",
    "target_folder": "Archive",
    "uid": "100"
  }
}
```

### Delete

#### `delete_email`
Delete email (marks as Deleted and expunges).

```json
{
  "name": "delete_email",
  "arguments": {
    "folder": "INBOX",
    "message_id": "1"
  }
}
```

### SMTP Sending

#### `send_email`
Send an email with optional HTML body and attachments.

```json
{
  "name": "send_email",
  "arguments": {
    "to": ["recipient@example.com"],
    "subject": "Email Subject",
    "body_text": "Plain text body",
    "body_html": "<p>HTML body</p>",
    "cc": ["cc@example.com"],
    "bcc": ["bcc@example.com"],
    "attachments": [
      {
        "filename": "document.pdf",
        "content_type": "application/pdf",
        "data_base64": "JVBERi0xLjQK..."
      }
    ]
  }
}
```

**Sending Attachments:**

Encode file content as base64:

```python
import base64

with open("report.zip", "rb") as f:
    data_base64 = base64.b64encode(f.read()).decode()

# Then use in MCP call
```

**Common Content Types:**
| File Type | Content Type |
|-----------|--------------|
| PDF | `application/pdf` |
| ZIP | `application/zip` |
| Excel | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` |
| Word | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` |
| Image (PNG) | `image/png` |
| Image (JPEG) | `image/jpeg` |
| Text | `text/plain` |

#### `send_reply`
Reply to an email.

```json
{
  "name": "send_reply",
  "arguments": {
    "to": ["recipient@example.com"],
    "subject": "Re: Original Subject",
    "body_text": "Reply text",
    "reply_to_message_id": "<original@example.com>",
    "quote_original": true
  }
}
```

#### `send_forward`
Forward an email to another recipient.

```json
{
  "name": "send_forward",
  "arguments": {
    "to": ["forward@example.com"],
    "subject": "Fwd: Original Subject",
    "original_folder": "INBOX",
    "original_message_id": "1",
    "body_text": "Here is the forwarded email:"
  }
}
```

### Utilities

#### `get_current_date`
Get current date and time.

```json
{
  "name": "get_current_date",
  "arguments": {}
}
```

## Skills

项目包含一个 OpenClaw skill，帮助用户更好地使用邮件服务。

### 安装 Skill

```bash
# 复制到 OpenClaw skills 目录
cp -r skills/mail-mcp ~/.openclaw/skills/
```

### Skill 功能

- 自动检查 mail-mcp 是否已安装
- 提供常见邮箱配置示例
- mcporter 使用示例

详见 [skills/mail-mcp/SKILL.md](skills/mail-mcp/SKILL.md)

## Testing

```bash
# Install test dependencies
pip install -e ".[dev]"

# Run all tests
pytest tests/ -v

# Run integration tests only
pytest tests/integration/ -v

# Run SMTP tests
pytest tests/integration/test_smtp_server.py -v
```

**Test Status:**
- SMTP Tests: 21 passed ✅
- IMAP Integration: 17 passed ✅
- Unit Tests: 64 passed (some mock issues in legacy tests)

## Project Structure

```
imap-mcp-server/
├── src/
│   └── imap_mcp/
│       ├── __init__.py
│       ├── __main__.py
│       ├── server.py           # MCP server & IMAP client
│       └── smtp/               # SMTP module
│           ├── __init__.py     # Exports & Attachment class
│           ├── connection.py   # SMTP connection management
│           ├── auth.py         # Authentication (PLAIN/LOGIN/OAuth2)
│           ├── errors.py       # Custom exceptions
│           └── operations/
│               ├── __init__.py
│               ├── message.py  # Email message building
│               └── send.py     # send_email/reply/forward
├── tests/
│   ├── integration/
│   │   ├── test_server.py      # IMAP integration tests
│   │   └── test_smtp_server.py # SMTP integration tests
│   └── unit/
│       ├── test_smtp.py        # SMTP unit tests
│       └── ...
├── specs/
│   └── smtp-spec.md            # SMTP specification
├── pyproject.toml
└── README.md
```

## Error Handling

All tools return structured responses. Errors are returned as:

```json
{
  "error": "Error message description"
}
```

SMTP errors include specific exception types:
- `SMTPConnectionError` - Connection failed
- `SMTPAuthError` - Authentication failed
- `SMTPSendError` - Send failed
- `SMTPRecipientsError` - Invalid recipients

## Supported Email Providers

| Provider | IMAP Host | SMTP Host | Notes |
|----------|-----------|-----------|-------|
| Gmail | `imap.gmail.com` | `smtp.gmail.com` | Requires App Password |
| Outlook | `outlook.office365.com` | `smtp.office365.com` | |
| 阿里云企业邮箱 | `mail.qiye.aliyun.com` | `smtp.qiye.aliyun.com` | |
| 腾讯企业邮箱 | `imap.exmail.qq.com` | `smtp.exmail.qq.com` | |
| QQ 邮箱 | `imap.qq.com` | `smtp.qq.com` | Requires authorization code |

## License

MIT