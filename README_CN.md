# Mail MCP Server

[English](README.md) | [中文](README_CN.md)

基于 MCP (Model Context Protocol) 的邮件管理服务。通过标准化的 MCP 接口提供完整的 IMAP 邮件操作和 SMTP 发送功能。

## 功能特性

- **文件夹管理**：列出、创建、删除、重命名邮件文件夹
- **邮件搜索**：支持复杂 IMAP 搜索条件（FROM、TO、SUBJECT、UNSEEN 等）
- **邮件操作**：获取邮件详情，包含正文和附件
- **标记操作**：标记已读/未读、星标/取消星标
- **移动/复制**：在文件夹间移动或复制邮件
- **删除**：删除邮件并执行 expunge
- **SMTP 发送**：发送带附件的邮件、回复、转发
  - SSL (465) 和 STARTTLS (587) 支持
  - 纯文本/HTML 双格式
  - 文件附件
  - OAuth2 认证（支持 Gmail 等）

## 安装

```bash
# 方式一：从 GitHub 安装（推荐）
pip install git+https://github.com/AdJIa/mail-mcp-server.git

# 方式二：克隆后安装
git clone https://github.com/AdJIa/mail-mcp-server.git
cd mail-mcp-server
pip install -e .

# 验证安装
which mail-mcp
```

## 配置

通过环境变量配置：

### IMAP 设置

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `IMAP_HOST` | IMAP 服务器地址 | `imap.example.com` |
| `IMAP_PORT` | IMAP 端口 | `993` |
| `EMAIL_USER` | 邮箱账号 | - |
| `EMAIL_PASSWORD` | 邮箱密码 | - |
| `IMAP_SSL` | 启用 SSL | `true` |

### SMTP 设置

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SMTP_HOST` | SMTP 服务器地址 | `smtp.example.com` |
| `SMTP_PORT` | SMTP 端口 | `465` |
| `EMAIL_USER` | 邮箱账号（同 IMAP） | - |
| `EMAIL_PASSWORD` | 邮箱密码（同 IMAP） | - |
| `SMTP_SSL` | 启用 SSL/TLS (端口 465) | `true` |
| `SMTP_STARTTLS` | 启用 STARTTLS (端口 587) | `false` |

### 常见邮箱配置示例

```bash
# 阿里云企业邮箱
export IMAP_HOST=mail.qiye.aliyun.com
export IMAP_PORT=993
export EMAIL_USER=your.email@company.com
export EMAIL_PASSWORD=your-password
export IMAP_SSL=true
export SMTP_HOST=smtp.qiye.aliyun.com
export SMTP_PORT=465
export SMTP_SSL=true

# Gmail（需要 App Password）
export IMAP_HOST=imap.gmail.com
export SMTP_HOST=smtp.gmail.com
export EMAIL_PASSWORD=your-app-password

# QQ 邮箱（需要授权码）
export IMAP_HOST=imap.qq.com
export SMTP_HOST=smtp.qq.com
export EMAIL_PASSWORD=your-auth-code
```

> **注意**：Gmail 需要使用 [应用专用密码](https://support.google.com/accounts/answer/185833)。

### mcporter 配置

在 `~/.mcporter/mcporter.json` 中添加：

```json
{
  "mcpServers": {
    "mail-mcp": {
      "command": "mail-mcp",
      "env": {
        "IMAP_HOST": "mail.qiye.aliyun.com",
        "IMAP_PORT": "993",
        "EMAIL_USER": "your.email@company.com",
        "EMAIL_PASSWORD": "your-password",
        "IMAP_SSL": "true",
        "SMTP_HOST": "smtp.qiye.aliyun.com",
        "SMTP_PORT": "465",
        "SMTP_SSL": "true"
      }
    }
  }
}
```

## 使用方式

### 命令行启动

```bash
# 启动 MCP 服务
mail-mcp
```

### mcporter 调用

```bash
# 列出文件夹
mcporter call mail-mcp.list_folders

# 搜索邮件
mcporter call mail-mcp.search_emails --args '{"folder": "INBOX", "limit": 10}'

# 发送邮件
mcporter call mail-mcp.send_email --args '{
  "to": ["recipient@example.com"],
  "subject": "测试邮件",
  "body_text": "这是邮件内容"
}'

# 发送带附件的邮件
mcporter call mail-mcp.send_email --args '{
  "to": ["recipient@example.com"],
  "subject": "带附件的邮件",
  "body_text": "请查收附件",
  "attachments": [{
    "filename": "report.pdf",
    "content_type": "application/pdf",
    "data_base64": "JVBERi0xLjQK..."
  }]
}'
```

## MCP 工具列表

### 文件夹管理

| 工具 | 功能 |
|------|------|
| `list_folders` | 列出所有文件夹 |
| `create_folder` | 创建文件夹 |
| `delete_folder` | 删除文件夹 |
| `rename_folder` | 重命名文件夹 |

### 邮件操作

| 工具 | 功能 |
|------|------|
| `search_emails` | 搜索邮件 |
| `get_email` | 获取邮件详情 |

### 标记操作

| 工具 | 功能 |
|------|------|
| `mark_read` | 标记已读 |
| `mark_unread` | 标记未读 |
| `mark_flagged` | 添加星标 |
| `unmark_flagged` | 移除星标 |

### 移动/复制/删除

| 工具 | 功能 |
|------|------|
| `move_email` | 移动邮件 |
| `copy_email` | 复制邮件 |
| `delete_email` | 删除邮件 |

### SMTP 发送

| 工具 | 功能 |
|------|------|
| `send_email` | 发送邮件（支持附件） |
| `send_reply` | 回复邮件 |
| `send_forward` | 转发邮件 |

### 工具

| 工具 | 功能 |
|------|------|
| `get_current_date` | 获取当前时间 |

## 发送附件

附件需要 base64 编码：

```python
import base64

# 读取文件并编码
with open("report.pdf", "rb") as f:
    data_base64 = base64.b64encode(f.read()).decode()

# 在 MCP 调用中使用
```

### 常见 Content-Type

| 文件类型 | Content-Type |
|---------|--------------|
| PDF | `application/pdf` |
| ZIP | `application/zip` |
| Excel | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` |
| Word | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` |
| PNG 图片 | `image/png` |
| JPEG 图片 | `image/jpeg` |
| 文本 | `text/plain` |

## 支持的邮箱服务商

| 服务商 | IMAP 地址 | SMTP 地址 | 备注 |
|--------|----------|----------|------|
| Gmail | `imap.gmail.com` | `smtp.gmail.com` | 需要 App Password |
| Outlook | `outlook.office365.com` | `smtp.office365.com` | |
| 阿里云企业邮箱 | `mail.qiye.aliyun.com` | `smtp.qiye.aliyun.com` | |
| 腾讯企业邮箱 | `imap.exmail.qq.com` | `smtp.exmail.qq.com` | |
| QQ 邮箱 | `imap.qq.com` | `smtp.qq.com` | 需要授权码 |

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

## 测试

```bash
# 安装测试依赖
pip install -e ".[dev]"

# 运行所有测试
pytest tests/ -v

# 仅运行集成测试
pytest tests/integration/ -v

# 仅运行 SMTP 测试
pytest tests/integration/test_smtp_server.py -v
```

**测试状态：**
- SMTP 测试：21 passed ✅
- IMAP 集成测试：17 passed ✅
- 单元测试：64 passed

## 项目结构

```
mail-mcp-server/
├── src/
│   └── imap_mcp/
│       ├── __init__.py
│       ├── __main__.py
│       ├── server.py           # MCP 服务 & IMAP 客户端
│       └── smtp/               # SMTP 模块
│           ├── __init__.py     # 导出 & Attachment 类
│           ├── connection.py   # SMTP 连接管理
│           ├── auth.py         # 认证 (PLAIN/LOGIN/OAuth2)
│           ├── errors.py       # 自定义异常
│           └── operations/
│               ├── __init__.py
│               ├── message.py  # 邮件构建
│               └── send.py     # send_email/reply/forward
├── tests/
│   ├── integration/
│   │   ├── test_server.py      # IMAP 集成测试
│   │   └── test_smtp_server.py # SMTP 集成测试
│   └── unit/
│       ├── test_smtp.py        # SMTP 单元测试
│       └── ...
├── skills/
│   └── mail-mcp/
│       ├── SKILL.md            # Skill 文档
│       └── install.sh          # 安装脚本
├── specs/
│   └── smtp-spec.md            # SMTP 规格文档
├── pyproject.toml
├── README.md                   # 英文文档
└── README_CN.md                # 中文文档
```

## 错误处理

所有工具返回结构化响应。错误格式：

```json
{
  "error": "错误描述"
}
```

SMTP 错误包含特定异常类型：
- `SMTPConnectionError` - 连接失败
- `SMTPAuthError` - 认证失败
- `SMTPSendError` - 发送失败
- `SMTPRecipientsError` - 收件人无效

## 许可证

MIT