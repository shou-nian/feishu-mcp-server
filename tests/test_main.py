"""根目录启动入口测试。"""

import main as root_main
from src.main import main as application_main


def test_root_main_reuses_application_entrypoint() -> None:
    assert root_main.main is application_main
