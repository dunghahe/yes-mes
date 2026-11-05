# Vận hành khóa mã hóa TOTP

## Xác minh Cloudflare Access

Trong production, cấu hình `CLOUDFLARE_ACCESS_TEAM_DOMAIN` (dạng `https://<team>.cloudflareaccess.com`) và `CLOUDFLARE_ACCESS_AUDIENCE` (AUD tag của ứng dụng) trong `.env` được bảo vệ. App không khởi động ở production nếu thiếu một trong hai giá trị; khi bật cấu hình, mọi request phải có `Cf-Access-Jwt-Assertion` hợp lệ. App xác minh RS256, chữ ký, issuer, audience, thời hạn và thời điểm bắt đầu hiệu lực bằng JWKS tại `/cdn-cgi/access/certs`; bộ khóa cache tối đa 5 phút để nhận khóa luân phiên.

Lấy AUD tag từ cấu hình ứng dụng Self-hosted trong Cloudflare Zero Trust. Không ghi assertion JWT vào log. Hướng dẫn Cloudflare: [Validate JWTs](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/).

## Cấu hình backup hằng ngày

Đặt `BACKUP_DIR`, `OFFSITE_BACKUP_DIR` và `AGE_RECIPIENT` trong môi trường cron/systemd; lưu khóa riêng age ngoài máy chủ ứng dụng. Đặt lịch cron hằng ngày lúc 02:00 UTC và lưu kết quả để theo dõi:

```cron
0 2 * * * cd /opt/mes && BACKUP_DIR=/var/backups/mes OFFSITE_BACKUP_DIR=/mnt/backup-host/mes AGE_RECIPIENT=age1... ./scripts/backup-postgres.sh >> /var/log/mes-backup.log 2>&1
```

Chi tiết khôi phục: `docs/backup-operations.md`.

## Tạo khóa ban đầu

Tạo khóa Fernet trong môi trường tin cậy:

```sh
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Đặt giá trị vào `TOTP_ENCRYPTION_KEYS` trong secret store hoặc file môi trường được bảo vệ. Không commit giá trị này, không đưa vào log. Sao lưu khóa riêng, mã hóa và cất ngoài máy chủ; nếu mất khóa, không thể giải mã bí mật TOTP hiện có.

## Xoay khóa

1. Tạo khóa mới, sao lưu an toàn khóa mới và cũ.
2. Đặt `TOTP_ENCRYPTION_KEYS` thành `khóa_mới,khóa_cũ` (khóa đầu danh sách dùng để mã hóa mới).
3. Khởi động lại ứng dụng và chạy `docker compose exec app python -m scripts.rotate_totp_key` trên máy chủ.
4. Kiểm tra lệnh báo số tài khoản đã xử lý và xác nhận đăng nhập TOTP hoạt động.
5. Bỏ khóa cũ khỏi cấu hình, khởi động lại ứng dụng, rồi kiểm tra TOTP lần nữa.
6. Chỉ hủy bản sao khóa cũ theo quy trình lưu trữ bí mật sau khi backup mã hóa mới đã được xác nhận.

Lệnh xoay ghi audit cho từng tài khoản nhưng không ghi bí mật TOTP hoặc giá trị khóa vào audit.
