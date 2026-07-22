# AGENTS.md

## 项目目标

你需要自主完成一个 Python 实现的飞书 MCP Server。

该 MCP Server 作为 MCP Server 端运行，由 Codex 作为 MCP Client 调用。

最终目标：

通过 MCP 协议，让 Codex 能够操作飞书文档：

1. 读取飞书文档内容
2. 更新飞书文档内容
3. 创建新的飞书文档

整体架构：

```
Codex
 |
 | MCP Protocol
 |
Python Feishu MCP Server
 |
 | HTTP API
 |
Feishu Open Platform API
```

---

# 一、最高优先级规则

## 1. 技术栈要求

必须使用：

- Python 3.11+
- MCP SDK
- uv 管理 Python 环境和依赖
- asyncio 异步实现
- httpx 作为 HTTP Client

禁止：

- 使用 requests
- 使用同步阻塞 HTTP 请求
- 引入没有必要的大型框架

---

## 2. 项目结构要求

必须保持清晰分层：

```
feishu-mcp-server
│
├── AGENTS.md
├── README.md
├── pyproject.toml
├── .env.example
│
├── src
│   │
│   ├── main.py                 # MCP Server入口
│   │
│   ├── config
│   │   └── settings.py         # 配置管理
│   │
│   ├── mcp
│   │   └── tools.py            # MCP Tool定义
│   │
│   ├── feishu
│   │   │
│   │   ├── client.py           # 飞书API客户端
│   │   ├── auth.py             # 飞书鉴权
│   │   └── document.py         # 文档业务封装
│   │
│   ├── models
│   │   └── schemas.py           # 数据模型
│   │
│   └── utils
│       └── logger.py
│
└── tests
    │
    ├── test_auth.py
    ├── test_document.py
    └── test_mcp.py
```

禁止把所有代码写在一个文件。


---

# 二、开发流程要求

你必须按照以下顺序完成：

## Step 1：分析需求

首先确认：

- MCP Server需要暴露哪些tools
- 飞书开放平台对应API
- 鉴权流程
- 请求和响应格式

输出设计说明。


---

## Step 2：初始化项目

创建：

- pyproject.toml
- uv环境
- 依赖管理

依赖至少包括：

- mcp
- httpx
- pydantic
- pydantic-settings
- python-dotenv

---

# 三、飞书鉴权要求

## 使用飞书智能体应用鉴权

禁止使用：

- 用户OAuth
- Authorization Code Flow

必须使用：

```
App ID
+
App Secret
```

获取：

```
tenant_access_token
```

流程：

```
App ID
   |
   |
App Secret
   |
   v

POST
/open-apis/auth/v3/tenant_access_token/internal

   |
   v

tenant_access_token

   |
   v

调用文档API
```

---

## 配置方式

使用环境变量：

```
FEISHU_APP_ID=
FEISHU_APP_SECRET=
```

提供：

```
.env.example
```

例如：

```
FEISHU_APP_ID=cli_xxxxx
FEISHU_APP_SECRET=xxxxx
```

---

# 四、飞书Client设计要求

封装统一客户端：

例如：

```python
class FeishuClient:

    async def request(
            self,
            method,
            url,
            **kwargs
    ):
        ...
```

要求：

- 自动获取tenant_access_token
- 自动添加Authorization Header
- token缓存
- token过期自动刷新

请求Header：

```
Authorization:
Bearer {tenant_access_token}
```

---

# 五、MCP Tools设计要求

MCP Server至少提供以下三个Tool。


---

# Tool 1：读取飞书文档

名称：

```
read_feishu_document
```

输入：

```json
{
  "document_id": "xxx"
}
```

功能：

调用飞书文档API：

读取：

- 文档标题
- 文档内容
- block结构

返回：

结构化Markdown。

示例：

```json
{
  "title": "xxx",
  "content": "markdown content"
}
```

---

# Tool 2：创建飞书文档

名称：

```
create_feishu_document
```

输入：

```json
{
  "title": "测试文档",
  "content": "hello world"
}
```

功能：

创建飞书文档。

返回：

```json
{
  "document_id": "",
  "url": ""
}
```

---

# Tool 3：更新飞书文档

名称：

```
update_feishu_document
```

输入：

```json
{
  "document_id": "xxx",
  "content": "new content"
}
```

功能：

更新文档正文。

要求：

支持：

- 全量替换
- Markdown转换

---

# 六、MCP实现要求

使用官方 MCP SDK。

Server启动方式：

stdio模式。

例如：

```bash
python -m src.main
```

Codex调用方式：

```
Codex
 |
 MCP Client
 |
stdio
 |
feishu-mcp-server
```

---

# 七、异常处理要求

所有异常必须：

1. 捕获
2. 转换成用户可理解错误

例如：

错误：

```
Feishu API error
code=99991663
```

转换：

```
飞书鉴权失败，请检查FEISHU_APP_ID和FEISHU_APP_SECRET
```

禁止直接打印traceback给MCP Client。


---

# 八、日志要求

日志：

- 输出stderr
- 不影响stdio MCP通信

禁止：

```python
print()
```

使用：

```
logging
```

---

# 九、测试要求

必须实现测试。

至少覆盖：

## auth

测试：

- token获取
- token缓存
- token刷新

## document

测试：

- 创建文档
- 查询文档
- 更新文档

## mcp

测试：

- tools是否注册成功
- 参数校验

测试：

```
pytest
```

HTTP 使用 Mock。禁止访问真实数据。

---

# 十、README要求

README必须包含：

## 1. 项目介绍

## 2. 环境准备

例如：

```
uv sync
```

## 3. 配置

说明：

```
FEISHU_APP_ID
FEISHU_APP_SECRET
```

## 4. 启动方式

例如：

```
python -m src.main
```

## 5. Codex MCP配置示例

提供：

```json
{
  "mcpServers": {
    "feishu": {
      "command": "python",
      "args": [
        "-m",
        "src.main"
      ],
      "env": {
        "FEISHU_APP_ID": "",
        "FEISHU_APP_SECRET": ""
      }
    }
  }
}
```

---

# 十一、代码质量要求

必须：

- 类型标注
- async/await
- 清晰异常定义
- 单元测试

禁止：

- 魔法字符串
- 重复代码
- 超大函数

---

# 十二、开发自主性要求

你(Codex)需要自主完成：

1. 调研飞书开放平台API
2. 设计代码结构
3. 创建项目文件
4. 实现代码
5. 编写测试
6. 编写README
7. 验证MCP Server可以被Codex调用

如果遇到不确定：

优先选择：

- 官方MCP规范
- 飞书开放平台官方API
- 简单可靠实现

不要停留在设计阶段，必须完成可运行代码。


---

# 十三、最终验收标准

完成后必须满足：

执行：

```
uv run python -m src.main
```

MCP Server正常启动。

Codex连接后可以调用：

```
read_feishu_document

create_feishu_document

update_feishu_document
```

并成功操作飞书文档。

项目达到：

```
可运行
可测试
可维护
可扩展
```

