"""用户 token 本地存储的纯 Mock 测试。"""

import json
import os
import stat
from pathlib import Path

from feishu_mcp.feishu.token_store import StoredUserToken, TokenStore


def _token() -> StoredUserToken:
    return StoredUserToken(
        access_token="u-access",
        refresh_token="ur-refresh",
        access_token_expires_at=2_000_000_000,
        refresh_token_expires_at=2_100_000_000,
        scope="docx:document offline_access",
    )


def test_token_store_round_trip_with_private_permissions(tmp_path: Path) -> None:
    path = tmp_path / ".feishu-mcp" / "tokens.json"
    store = TokenStore(path)

    store.save(_token())
    loaded = store.load()

    assert loaded == _token()
    assert json.loads(path.read_text(encoding="utf-8"))["access_token"] == "u-access"
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) & 0o077 == 0
    assert list(path.parent.glob("*.tmp")) == []


def test_missing_token_file_returns_none(tmp_path: Path) -> None:
    assert TokenStore(tmp_path / "missing.json").load() is None


def test_corrupt_token_file_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "tokens.json"
    path.write_text("{broken", encoding="utf-8")

    assert TokenStore(path).load() is None
