# Chuyển MES lên Linux bằng Docker Compose

Giao diện Jinja và backend chạy trong cùng image; PostgreSQL chạy trong container riêng. Dùng **compose.production.yaml** độc lập. Không ghép thêm compose.yaml của dev, vì tệp dev có bind mount và `--reload`.

## Chuẩn bị

1. Chép mã nguồn đã rà soát sang máy chủ có Docker Engine và Compose v2. Không chép `.env` vào Git hoặc image.
2. Tạo `.env.production` từ `.env.production.example`, đặt quyền `chmod 600 .env.production`.
3. Điền ba mật khẩu riêng cho bootstrap/runtime/migration; URL kết nối phải tương ứng. Nếu mật khẩu chứa ký tự đặc biệt, URL-encode phần mật khẩu trong URL.
4. Khi khôi phục dữ liệu cũ, **giữ đúng TOTP_ENCRYPTION_KEYS cũ**. Mật khẩu database có thể đổi theo máy mới; khóa mã hóa TOTP không được tự sinh thay thế.
5. Điền team domain và audience thực của ứng dụng Cloudflare Access. Cấu hình này bắt buộc; giá trị trong tệp mẫu chỉ để minh họa.

Các lệnh dưới chạy tại thư mục dự án trên Linux:

```sh
docker compose --env-file .env.production -f compose.production.yaml config --quiet
docker compose --env-file .env.production -f compose.production.yaml build app
docker compose --env-file .env.production -f compose.production.yaml up -d db
```

## Khôi phục dữ liệu hoặc cài mới

Chỉ khôi phục vào database mới, chưa có bảng nghiệp vụ. Bản dump không bao gồm khóa TOTP trong biến môi trường và cấu hình Cloudflare.

```sh
docker compose --env-file .env.production -f compose.production.yaml exec -T db sh -ec \
  'PGPASSWORD="$POSTGRES_PASSWORD" pg_restore --host=127.0.0.1 --username="$POSTGRES_USER" --role=mes_migrator --no-owner --exit-on-error --dbname="$POSTGRES_DB"' \
  < /duong-dan-bao-mat/mes.dump
```

Sau khi khôi phục, hoặc khi cài mới không có dữ liệu:

```sh
docker compose --env-file .env.production -f compose.production.yaml run --rm migrate
docker compose --env-file .env.production -f compose.production.yaml run --rm app python -m scripts.reconcile_order_status
```

Lệnh đối soát mặc định chỉ chạy thử, không lưu. Nếu báo có PO cần cập nhật theo quy tắc tự đóng/mở đã chốt, lưu và ghi audit bằng:

```sh
docker compose --env-file .env.production -f compose.production.yaml run --rm app python -m scripts.reconcile_order_status --apply
```

Chỉ với cài mới chưa có Admin, tạo tài khoản đầu tiên bằng CLI tương tác:

```sh
docker compose --env-file .env.production -f compose.production.yaml run --rm app python -m scripts.bootstrap_admin
```

Không chạy lệnh tạo Admin mới để thay thế Admin đã khôi phục. Kiểm tra quy trình đăng nhập/TOTP của tài khoản cũ bằng khóa cũ.

## Khởi chạy và kiểm tra

```sh
docker compose --env-file .env.production -f compose.production.yaml up -d app
docker compose --env-file .env.production -f compose.production.yaml ps
docker compose --env-file .env.production -f compose.production.yaml exec -T app python -m scripts.healthcheck
```

Nếu `cloudflared` chạy trực tiếp trên cùng Linux host, trỏ tunnel vào `http://127.0.0.1:8000`. Nếu chạy cloudflared trong container riêng, cấu hình mạng riêng phù hợp; `127.0.0.1` trong container đó không phải host. Không mở cổng PostgreSQL ra ngoài.

App kiểm chữ ký, hạn và audience của JWT Access. Truy cập HTTP trực tiếp thiếu JWT trả 403 là đúng; healthcheck trong container kiểm tra tiến trình web và kết nối DB mà không nới bảo vệ HTTP. Asset dùng URL tương đối để tránh mixed content khi Tunnel kết thúc HTTPS ở phía ngoài.

Nghiệm thu trên hostname thật:

- Đăng nhập từng vai trò, Admin có TOTP, đăng xuất, phiên không hoạt động 60 phút.
- Tạo PO/lịch/yêu cầu phôi; in biểu; xác nhận giao; nhập sản lượng; nhập QC theo lô; cấp phiếu sửa và QC lại.
- In thử A4 bằng máy in thật; kiểm QR, số trang, vùng ghi tay.
- Kiểm số liệu PO và trạng thái tự đóng/mở với một PO mẫu. FULL/BAVIA_ONLY vẫn cần QC Bavia cho số thành phẩm; màn QC Bavia đang được hoãn theo phạm vi đã chốt.

## Backup và quay lại bản trước

Thiết lập backup hằng ngày theo `docs/security-operations.md` và `docs/backup-operations.md`, thêm hai biến để chọn đúng compose production:

```sh
MES_COMPOSE_FILE=compose.production.yaml MES_ENV_FILE=.env.production \
  BACKUP_DIR=/var/backups/mes OFFSITE_BACKUP_DIR=/mnt/backup-host/mes \
  AGE_RECIPIENT=age1... bash scripts/backup-postgres.sh
```

`OFFSITE_BACKUP_DIR` phải là vị trí ngoài máy chủ đã gắn thực sự. Việc thử restore cục bộ không chứng minh lịch backup, ổ ngoài hoặc khóa age của máy chủ đã được thiết lập.

Trước mỗi lần nâng cấp: backup DB, giữ image tag cũ, ghi revision Alembic. Nếu lỗi app, đổi `MES_IMAGE` về image cũ rồi `up -d --no-build app` khi schema tương thích. Nếu cần lùi schema hoặc restore, thực hiện trong thời gian bảo trì theo backup đã kiểm tra; không chạy `downgrade base` trên dữ liệu thật.
