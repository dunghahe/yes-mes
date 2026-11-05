from sqlalchemy import select

from app.core.db import SessionLocal
from app.modules.auth.models import AuditLog, User
from app.modules.auth.totp import rotate_encrypted_totp_secret


def main() -> None:
    rotated_count = 0
    with SessionLocal.begin() as db:
        users = db.scalars(
            select(User).where(User.totp_secret_encrypted.is_not(None)).with_for_update()
        )
        for user in users:
            user.totp_secret_encrypted = rotate_encrypted_totp_secret(user.totp_secret_encrypted)
            user.version += 1
            db.add(
                AuditLog(
                    table_name="users",
                    record_id=user.id,
                    action="update",
                    old_values={"totp_secret_encrypted": "[đã mã hóa]"},
                    new_values={"totp_secret_encrypted": "[đã mã hóa bằng khóa hiện hành]"},
                    reason="Xoay khóa mã hóa TOTP",
                    actor_id=None,
                )
            )
            rotated_count += 1
    print(f"Đã xoay khóa mã hóa TOTP cho {rotated_count} tài khoản.")


if __name__ == "__main__":
    main()
