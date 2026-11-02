"""命令行参数与登录入口的纯 Mock 测试。"""

from feishu_mcp.cli import build_parser


def test_default_command_runs_server() -> None:
    args = build_parser().parse_args([])

    assert args.command is None


def test_login_manual_command_parses_options() -> None:
    args = build_parser().parse_args(["login", "--manual", "--timeout", "30"])

    assert args.command == "login"
    assert args.manual is True
    assert args.timeout == 30
