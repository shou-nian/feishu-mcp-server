# 飞书 MCP Server

一个使用 Python、官方 MCP SDK、`asyncio` 和飞书官方 `lark-oapi` SDK 实现的飞书文档 MCP Server。它通过 stdio 与 Codex 等 MCP Client 通信，通过飞书开放平台 Docx API 读取、创建和更新文档。

## 功能与设计

Server 暴露四个 Tool：

- `read_feishu_document(document_id)`：读取标题、完整 block 列表，并返回包含表格的 Markdown。
- `create_feishu_document(title, content)`：创建文档，将 Markdown（含表格）转为飞书 blocks 后写入。
- `update_feishu_document(document_id, content)`：删除文档根节点下的原正文，然后以 Markdown（含表格）全量替换。
- `append_feishu_document(document_id, content)`：在已有文档末尾追加普通文本、Markdown 或表格，不删除或改写现有内容。

追加 Tool 的输入示例：

```json
{
  "document_id": "doxcnxxxxxxxxxxxx",
  "content": "## 新增章节\n\n追加正文\n\n| 项目 | 状态 |\n| --- | --- |\n| 文档 | 完成 |"
}
```

追加操作只读取 block 列表来确定文档根节点的末尾位置，然后创建新 blocks；不会调用删除接口，也不会通过“读取后整体重写”的方式更新文档。已有的段落、表格、图片以及当前未支持转换的其他根级 blocks 都会保留。普通文本本身是合法 Markdown，可直接作为 `content` 传入。

对应的飞书 API：

- `POST /open-apis/auth/v3/tenant_access_token/internal`：使用 App ID 和 App Secret 获取 `tenant_access_token`。
- `GET /open-apis/docx/v1/documents/{document_id}`：读取文档元信息。
- `GET /open-apis/docx/v1/documents/{document_id}/blocks`：分页读取 block 结构。
- `POST /open-apis/docx/v1/documents`：创建文档。
- `POST /open-apis/docx/v1/documents/{document_id}/blocks/{block_id}/children`：写入 blocks。
- `DELETE /open-apis/docx/v1/documents/{document_id}/blocks/{block_id}/children/batch_delete`：删除旧正文。

鉴权仅使用飞书自建应用的 `tenant_access_token`，不使用用户 OAuth。应用凭证、Token 获取与缓存、API 请求序列化均由飞书官方 `lark-oapi` SDK 管理；业务代码调用 SDK 提供的 `aget`、`alist`、`acreate`、`abatch_delete` 等原生异步接口，不再自行发送 HTTP 请求。

当前 Markdown 转换支持普通段落、1—9 级标题、无序/有序列表、任务列表、引用、分隔线、代码块、标准管道表格，以及粗体、删除线、行内代码和链接。未支持的复杂飞书 block 仍会保留在 `blocks` 原始响应中，但不会凭空转换成 Markdown。

表格示例：

```markdown
| 姓名 | 年龄 |
| --- | --- |
| 小明 | 18 |
```

写入时第一行会作为飞书表格表头；`<br>` 会在单元格内转换为换行。读取飞书表格时会根据 table block 的行列属性、cell IDs 和单元格子 blocks 重建 Markdown。Markdown 本身不能完整表达合并单元格、精确列宽或复杂嵌套 block，这些信息仍保留在 Tool 返回的原始 `blocks` 字段中。

## 环境准备

要求：

- Python 3.11 或更高版本
- [uv](https://docs.astral.sh/uv/)
- 已创建并启用的飞书企业自建应用

同步虚拟环境和锁文件：

```bash
uv sync
```

飞书应用需要开通与 Docx 文档读取、创建、编辑相关的权限，并发布可用版本。要读取或更新已有文档，还需要确保应用对目标文档具有访问权限。

## 配置

复制 `.env.example` 为 `.env`，填写以下必需变量：

```dotenv
FEISHU_APP_ID=cli_xxxxx
FEISHU_APP_SECRET=xxxxx
```

飞书开放平台地址固定为官方 `https://open.feishu.cn`，由代码配置，不需要环境变量。

可选变量：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `FEISHU_DOCUMENT_URL_BASE` | `https://feishu.cn/docx` | 创建结果中的文档 URL 前缀；私有化域名可覆盖 |
| `FEISHU_REQUEST_TIMEOUT` | `15` | HTTP 超时秒数 |
| `LOG_LEVEL` | `INFO` | stderr 日志级别 |

不要提交真实的 App Secret；`.env` 已加入 `.gitignore`。

## 启动

```bash
uv run feishu-mcp
```

`feishu-mcp` 是通过 `project.scripts` 安装的推荐入口。根目录入口 `uv run python main.py` 仍可兼容使用。

Server 使用 stdio 传输。日志只写入 stderr，不会污染 MCP 协议的 stdout。stdin 正常关闭、任务取消，或进程收到 `SIGINT`/`SIGTERM` 时，Server 会取消服务任务并退出 MCP 生命周期。

缺少配置时进程会输出简明错误并以状态码 `2` 退出，不会把 Python traceback 返回给 MCP Client。

## Codex MCP 配置示例

推荐让 Codex 直接通过 uv 启动已安装的 `feishu-mcp` 命令：

```json
{
  "mcpServers": {
    "feishu": {
      "command": "uv",
      "args": [
        "--directory",
        "D:\\project\\feishu-mcp-server",
        "run",
        "feishu-mcp"
      ],
      "env": {
        "FEISHU_APP_ID": "cli_xxxxx",
        "FEISHU_APP_SECRET": "xxxxx"
      }
    }
  }
}
```

如果 Codex 已经在项目根目录运行，也可以省略 `--directory`：

```json
{
  "mcpServers": {
    "feishu": {
      "command": "uv",
      "args": [
        "run",
        "feishu-mcp"
      ],
      "env": {
        "FEISHU_APP_ID": "cli_xxxxx",
        "FEISHU_APP_SECRET": "xxxxx"
      }
    }
  }
}
```

## 测试与质量检查

```bash
uv run pytest
uv run ruff check src tests
```

测试中的所有飞书调用都使用官方 SDK 模型、`AsyncMock` 或内存 fake client，不会访问真实飞书数据。覆盖范围包括 SDK 客户端配置、鉴权与 API 错误转换，文档创建/读取/全量更新/追加、分页、Markdown 与表格转换和表格单元格写入，以及 MCP Tool 注册、参数校验、错误转换和优雅退出。追加测试还会确认没有删除调用，且已有表格的嵌套 blocks 不会影响根节点末尾索引。

## 项目结构

```text
main.py                          # 兼容的项目根目录入口
src/
└── feishu_mcp/                  # 可安装的 Python 包
    ├── __init__.py              # feishu-mcp console script 入口
    ├── main.py                  # stdio 生命周期和优雅退出
    ├── config/settings.py       # 环境变量配置
    ├── feishu/
    │   ├── auth.py              # lark-oapi Client 与应用鉴权配置
    │   ├── client.py            # 官方 SDK Docx 异步接口封装
    │   ├── document.py          # Docx 业务、Markdown 与表格转换
    │   └── errors.py            # 用户友好的异常
    ├── tools/tools.py           # MCP Tools 注册（避免与官方 mcp 包冲突）
    ├── models/schemas.py        # 结构化响应模型
    └── utils/logger.py          # stderr 日志
```
