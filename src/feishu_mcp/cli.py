"""飞书 MCP Server 的命令行入口与用户授权登录。"""

import argparse
import logging
import sys
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Sequence
from urllib.parse import parse_qs, urlsplit

from pydantic import ValidationError

from feishu_mcp.config.settings import Settings, get_settings
from feishu_mcp.feishu.auth import build_lark_client
from feishu_mcp.feishu.errors import FeishuAuthError
from feishu_mcp.feishu.oauth import FeishuOAuthService
from feishu_mcp.feishu.token_store import StoredUserToken
from feishu_mcp.utils.logger import configure_logging

LOGGER = logging.getLogger(__name__)
CALLBACK_TIMEOUT_SECONDS = 300


def build_parser() -> argparse.ArgumentParser:
    """构造 CLI 参数解析器。"""

    parser = argparse.ArgumentParser(prog="feishu-mcp")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("serve", help="启动 stdio MCP Server（默认）")
    login_parser = subparsers.add_parser("login", help="使用飞书用户身份完成 OAuth 授权")
    login_parser.add_argument(
        "--manual",
        action="store_true",
        help="不启动本地回调服务，改为手工粘贴授权码",
    )
    login_parser.add_argument(
        "--timeout",
        type=int,
        default=CALLBACK_TIMEOUT_SECONDS,
        help="本地回调等待秒数，默认 300",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """解析命令并启动 Server 或 OAuth 登录。"""

    args = build_parser().parse_args(argv)
    command = args.command or "serve"
    try:
        settings = get_settings()
        configure_logging(settings.log_level)
        if command == "login":
            login(settings, manual=args.manual, timeout=args.timeout)
            return
        _run_stdio(settings)
    except KeyboardInterrupt:
        LOGGER.info("飞书 MCP Server 已停止")
    except ValidationError:
        configure_logging()
        LOGGER.error("配置错误：请设置有效的 FEISHU_APP_ID 和 FEISHU_APP_SECRET")
        raise SystemExit(2) from None
    except FeishuAuthError as exc:
        LOGGER.error("%s", exc)
        raise SystemExit(2) from None
    except Exception as exc:
        LOGGER.error("飞书 MCP Server 启动或运行失败：%s", exc)
        raise SystemExit(1) from None


def login(settings: Settings, *, manual: bool, timeout: int = CALLBACK_TIMEOUT_SECONDS) -> None:
    """完成交互式授权并保存用户 token。"""

    if settings.feishu_auth_mode != "user":
        LOGGER.warning("当前 FEISHU_AUTH_MODE=tenant；登录后请改为 user 才会使用用户身份")
    sdk_client = build_lark_client(settings)
    oauth = FeishuOAuthService.from_settings(settings, sdk_client)
    authorization_url, state = oauth.build_authorization_url()

    if manual:
        _write_stderr("请在浏览器打开以下链接完成授权：\n")
        _write_stderr(f"{authorization_url}\n\n")
        _write_stderr("回调页面无法访问时，请从浏览器地址栏复制 code 参数值。\n")
        code = input("授权码: ").strip()
    else:
        code = _wait_for_callback(
            oauth,
            authorization_url=authorization_url,
            expected_state=state,
            redirect_uri=settings.feishu_redirect_uri,
            timeout=timeout,
        )

    token = oauth.exchange_authorization_code(code)
    _report_login_success(settings.feishu_token_file, token)


def _run_stdio(settings: Settings) -> None:
    import asyncio

    from feishu_mcp.main import run_server

    asyncio.run(run_server())


def _wait_for_callback(
    oauth: FeishuOAuthService,
    *,
    authorization_url: str,
    expected_state: str,
    redirect_uri: str,
    timeout: int,
) -> str:
    parsed = urlsplit(redirect_uri)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise FeishuAuthError(
            "自动回调仅支持 http://127.0.0.1 或 http://localhost；"
            "其他 redirect_uri 请使用 `feishu-mcp login --manual`"
        )
    port = parsed.port or 80
    callback_path = parsed.path or "/"
    result = _CallbackResult()

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            request = urlsplit(self.path)
            if request.path != callback_path:
                self.send_error(404, "Not Found")
                return
            parameters = parse_qs(request.query)
            state = _first(parameters, "state")
            if state != expected_state:
                result.error = "OAuth state 校验失败，请重新执行授权"
                result.event.set()
                self._respond(400, "授权状态校验失败，请关闭页面并重新登录。")
                return
            error = _first(parameters, "error")
            if error:
                result.error = error
                result.event.set()
                self._respond(400, "飞书授权失败，请返回终端重新执行登录。")
                return
            code = _first(parameters, "code")
            if not code:
                result.error = "飞书回调缺少授权码"
                result.event.set()
                self._respond(400, "回调缺少授权码，请重新登录。")
                return
            result.code = code
            result.event.set()
            self._respond(200, "飞书授权成功，可以关闭此页面并返回终端。")

        def _respond(self, status: int, message: str) -> None:
            body = f"<!doctype html><meta charset='utf-8'><p>{message}</p>".encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            LOGGER.debug("OAuth callback: " + format, *args)

    try:
        server = ThreadingHTTPServer((parsed.hostname or "127.0.0.1", port), CallbackHandler)
    except OSError as exc:
        raise FeishuAuthError(
            f"无法监听 OAuth 回调端口 {port}，请释放端口或使用 `feishu-mcp login --manual`"
        ) from exc

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _write_stderr("请在浏览器打开以下链接完成飞书授权：\n")
        _write_stderr(f"{authorization_url}\n\n")
        _write_stderr(f"等待回调：{redirect_uri}\n")
        if not result.event.wait(timeout):
            raise FeishuAuthError("等待飞书 OAuth 回调超时，请重新执行 `feishu-mcp login`")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    if result.error:
        raise FeishuAuthError(result.error)
    if not result.code:
        raise FeishuAuthError("飞书 OAuth 回调未返回授权码")
    return result.code


@dataclass(slots=True)
class _CallbackResult:
    event: threading.Event
    code: str | None = None
    error: str | None = None

    def __init__(self) -> None:
        self.event = threading.Event()


def _first(parameters: dict[str, list[str]], key: str) -> str | None:
    values = parameters.get(key)
    return values[0] if values else None


def _report_login_success(path: Path, token: StoredUserToken) -> None:
    scope = token.scope or "未返回"
    _write_stderr(f"飞书用户授权成功，token 已保存到 {path}\n")
    _write_stderr(f"授权 scope：{scope}\n")


def _write_stderr(message: str) -> None:
    sys.stderr.write(message)
    sys.stderr.flush()


__all__ = ["build_parser", "login", "main"]
