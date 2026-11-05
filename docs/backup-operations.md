# Sao lưu và khôi phục PostgreSQL

Script `scripts/backup-postgres.sh` tạo bản dump PostgreSQL mỗi lần chạy, mã hóa bản sao bằng `age`, giữ 14 ngày ở cả thư mục backup cục bộ và thư mục off-host. `OFFSITE_BACKUP_DIR` phải trỏ đến ổ đĩa hoặc mount nằm ngoài máy chủ ứng dụng; script không thể xác minh vị trí lưu trữ có thực sự ở máy khác.

## Cấu hình trên máy Linux

1. Cài Docker Compose và `age` trên máy chạy lịch backup.
2. Tạo khóa riêng `age` và bảo quản ngoài máy chủ ứng dụng:

   ```sh
   age-keygen -o /etc/mes/backup.agekey
   chmod 600 /etc/mes/backup.agekey
   age-keygen -y /etc/mes/backup.agekey
   ```

   Dùng chuỗi public recipient do lệnh cuối trả về làm `AGE_RECIPIENT`. Không đặt khóa riêng trên máy chủ ứng dụng.
3. Tạo mount lưu trữ off-host, rồi đặt `OFFSITE_BACKUP_DIR` trỏ vào mount đó. Cấu hình `BACKUP_DIR`, `OFFSITE_BACKUP_DIR` và `AGE_RECIPIENT` trong môi trường cron/systemd. Không đưa mật khẩu database vào môi trường script; Compose đọc `.env` riêng bên trong lệnh backup.
4. Chạy thử từ repo và kiểm tra hai dòng `Backup complete` cùng `Encrypted off-host copy complete`:

   ```sh
   BACKUP_DIR=/var/backups/mes \
   OFFSITE_BACKUP_DIR=/mnt/backup-host/mes \
   AGE_RECIPIENT=age1... \
   ./scripts/backup-postgres.sh
   ```
5. Đặt lịch chạy hằng ngày lúc 02:00 UTC bằng cron. Ghi stdout/stderr vào log và cảnh báo người vận hành nếu lệnh trả mã lỗi khác 0. Không ghi khóa riêng hay mật khẩu database vào log. Ví dụ cron có trong `docs/security-operations.md`.

## Khôi phục thử

Mỗi quý, sao chép một bản `.dump.age` sang máy khác, giải mã bằng khóa riêng `age`, rồi nạp vào một PostgreSQL 16 tạm:

```sh
age --decrypt --identity /path/to/backup.agekey --output mes-restore.dump mes-backup.dump.age
pg_restore --exit-on-error --clean --if-exists --no-owner --dbname "$RESTORE_DATABASE_URL" mes-restore.dump
```

Kiểm tra Alembic revision, số bản ghi mẫu và các view sau khi khôi phục. Khóa riêng chỉ dùng trên máy khôi phục tin cậy; không chép khóa vào cùng nơi lưu backup.
