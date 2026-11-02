"""用户 OAuth token 的本地安全持久化。"""

import json
import logging
import os
import stat
import subprocess
import tempfile
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

LOGGER = logging.getLogger(__name__)


class StoredUserToken(BaseModel):
    """持久化的用户访问凭证。"""

    access_token: str = Field(min_length=1)
    refresh_token: str = Field(min_length=1)
    access_token_expires_at: int = Field(gt=0)
    refresh_token_expires_at: int = Field(gt=0)
    scope: str = ""


class TokenStore:
    """以最小文件权限原子读写用户 token。"""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> StoredUserToken | None:
        """读取 token；文件不存在或损坏时返回 None。"""

        if not self.path.exists():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return StoredUserToken.model_validate(payload)
        except (OSError, json.JSONDecodeError, ValidationError):
            LOGGER.warning("用户 token 文件无效，将要求重新授权")
            return None

    def save(self, token: StoredUserToken) -> None:
        """原子写入 token，并将目录和文件权限限制为当前用户。"""

        directory = self.path.parent
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        _set_private_mode(directory, 0o700)

        temporary_path: Path | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                dir=directory,
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(token.model_dump(), stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            _set_private_mode(temporary_path, 0o600)
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()


def _set_private_mode(path: Path, mode: int) -> None:
    try:
        path.chmod(mode)
    except OSError as exc:
        LOGGER.warning("无法设置 token 文件权限 %s：%s", stat.filemode(mode), exc)
        return
    if os.name == "nt":
        _restrict_windows_acl(path)


def _restrict_windows_acl(path: Path) -> None:
    username = os.environ.get("USERNAME")
    domain = os.environ.get("USERDOMAIN")
    if not username:
        LOGGER.warning("无法确定当前 Windows 用户，token 文件 ACL 未收紧")
        return
    principal = f"{domain}\\{username}" if domain else username
    try:
        result = subprocess.run(
            [
                "icacls",
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"{principal}:F",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        LOGGER.warning("无法收紧 Windows token 文件 ACL：%s", exc)
        return
    if result.returncode != 0:
        LOGGER.warning("无法收紧 Windows token 文件 ACL：%s", result.stderr.strip())
