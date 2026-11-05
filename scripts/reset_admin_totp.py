from getpass import getpass

from sqlalchemy import select

from app.core.db import SessionLocal
from app.modules.auth.models import AuditLog, User
from app.modules.auth.service import revoke_user_sessions


def main() -> None:
    username = input("Tên đăng nhập Admin cần đặt lại TOTP: ").strip()
    confirmation = getpass("Nhập RESET-TOTP để xác nhận: ")
    if confirmation != "RESET-TOTP":
        raise SystemExit("Đã hủy; nội dung xác nhận không khớp.")

    with SessionLocal.begin() as db:
        user = db.scalar(
            select(User)
            .where(User.username == username, User.role == "admin", User.deleted_at.is_(None))
            .with_for_update()
        )
        if user is None:
            raise SystemExit("Không tìm thấy Admin đang hoạt động với tên đăng nhập này.")

        old_totp_enabled = user.totp_enabled
        user.totp_secret_encrypted = None
        user.totp_enabled = False
        user.totp_recovery_hashes = []
        user.totp_last_used_counter = None
        user.must_change_password = True
        user.version += 1
        revoke_user_sessions(db, user.id)
        db.add(
            AuditLog(
                table_name="users",
                record_id=user.id,
                action="update",
                old_values={"totp_enabled": old_totp_enabled},
                new_values={"totp_enabled": False, "must_change_password": True},
                reason="Đặt lại TOTP trực tiếp trên máy chủ theo yêu cầu hỗ trợ",
                actor_id=None,
            )
        )
    print("Đã đặt lại TOTP và thu hồi mọi phiên. Admin phải đổi mật khẩu và đăng ký TOTP mới.")


if __name__ == "__main__":
    main()
