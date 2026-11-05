from getpass import getpass

from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.modules.auth.models import AuditLog, User
from app.modules.auth.service import hash_password


def main() -> None:
    username = input("Tên đăng nhập Admin: ").strip()
    display_name = input("Tên hiển thị: ").strip()
    password = getpass("Mật khẩu mới: ")
    password_confirmation = getpass("Nhập lại mật khẩu: ")

    if not username or len(username) > 100:
        raise SystemExit("Tên đăng nhập phải có từ 1 đến 100 ký tự.")
    if not display_name or len(display_name) > 200:
        raise SystemExit("Tên hiển thị phải có từ 1 đến 200 ký tự.")
    if password != password_confirmation:
        raise SystemExit("Hai lần nhập mật khẩu không khớp.")

    with SessionLocal.begin() as db:
        db.execute(select(func.pg_advisory_xact_lock(6_753_214_090)))
        admin_count = db.scalar(select(func.count()).select_from(User).where(User.role == "admin"))
        if admin_count:
            raise SystemExit("Đã có tài khoản Admin; lệnh khởi tạo chỉ dùng được một lần.")

        user = User(
            username=username,
            display_name=display_name,
            password_hash=hash_password(password),
            role="admin",
            must_change_password=True,
        )
        db.add(user)
        db.flush()
        db.add(
            AuditLog(
                table_name="users",
                record_id=user.id,
                action="create",
                old_values=None,
                new_values={
                    "username": username,
                    "display_name": display_name,
                    "role": "admin",
                    "must_change_password": True,
                },
                reason="Khởi tạo Admin đầu tiên trên máy chủ",
                actor_id=None,
            )
        )

    print(
        "Đã tạo Admin đầu tiên. Tài khoản sẽ được yêu cầu đổi mật khẩu "
        "và thiết lập TOTP khi đăng nhập."
    )


if __name__ == "__main__":
    main()
