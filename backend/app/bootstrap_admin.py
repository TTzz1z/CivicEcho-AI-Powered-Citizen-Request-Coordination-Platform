"""Create the first local administrator for a fresh production installation."""
from argparse import ArgumentParser
from getpass import getpass
import re
import sys

from sqlalchemy import select, text

from .config import get_settings
from .database import SessionLocal
from .models import AuditLogModel, UserModel
from .security import hash_password


def bootstrap(username: str, display_name: str, password: str) -> None:
    if get_settings().app_env.strip().lower() not in {"production", "prod"}:
        raise SystemExit("此命令仅用于生产环境初始化。")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,100}", username) or username.lower().endswith("_local"):
        raise SystemExit("请输入有效的生产账号名，不能使用演示账号。")
    if not 1 <= len(display_name) <= 100 or not 16 <= len(password) <= 256:
        raise SystemExit("显示名应为 1–100 字符，口令应为 16–256 字符。")

    with SessionLocal.begin() as db:
        db.execute(text("SELECT pg_advisory_xact_lock(1068332491)"))
        if db.scalar(select(UserModel.id).where(UserModel.role == "admin").limit(1)) is not None:
            raise SystemExit("管理员已经初始化。请使用现有管理入口。")
        if db.scalar(select(UserModel.id).where(UserModel.username == username)) is not None:
            raise SystemExit("账号名已占用。")
        admin = UserModel(username=username, display_name=display_name, role="admin",
                          password_hash=hash_password(password), is_active=True)
        db.add(admin)
        db.flush()
        db.add(AuditLogModel(actor_type="system", action="bootstrap_admin", resource_type="user",
                             resource_id=str(admin.id), outcome="success"))


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("username")
    parser.add_argument("--display-name", required=True)
    args = parser.parse_args()
    if not sys.stdin.isatty():
        raise SystemExit("请在交互终端输入初始口令。")
    password = getpass("初始管理员口令: ")
    if password != getpass("再次输入口令: "):
        raise SystemExit("两次输入的口令不一致。")
    bootstrap(args.username, args.display_name.strip(), password)
    print("首位生产管理员已创建。")


if __name__ == "__main__":
    main()
