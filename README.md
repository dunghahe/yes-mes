# Hệ thống nhập liệu sản lượng, NG và OEE

Ứng dụng mới theo thiết kế v1.2. Repo YGC cũ chỉ dùng tham khảo giao diện và quy trình; không dùng lại mô hình lô hoặc SQLite.

## Môi trường phát triển

Phát triển trong Ubuntu WSL2 trên Windows. Docker Desktop cần bật WSL2 engine và tích hợp với Ubuntu.

1. Tạo file cấu hình dev từ mẫu: `cp .env.example .env`.
2. Đặt mật khẩu dev riêng cho `POSTGRES_PASSWORD`, `MES_APP_PASSWORD` và `MES_MIGRATOR_PASSWORD`; cập nhật hai URL tương ứng.
   Tạo `TOTP_ENCRYPTION_KEYS` bằng lệnh trong `docs/security-operations.md`.
3. Khởi động: `docker compose up --build`.
4. Chạy migration bằng service riêng: `docker compose run --rm migrate`.
5. Khởi tạo Admin đầu tiên bằng lệnh tương tác: `docker compose exec app python -m scripts.bootstrap_admin`.
   Nếu Admin mất cả thiết bị và mã dự phòng, đặt lại TOTP trực tiếp trên máy chủ bằng `docker compose exec app python -m scripts.reset_admin_totp`.
   Xoay khóa mã hóa TOTP theo hướng dẫn `docs/security-operations.md`.
6. Mở `http://localhost:${APP_PORT:-8000}` (mặc định cổng 8000). PostgreSQL chỉ truy cập trong mạng nội bộ Docker; dùng `docker compose exec db psql -U mes_bootstrap -d mes` khi cần mở psql.
7. Dừng: `docker compose down`. Muốn xóa dữ liệu dev cục bộ: `docker compose down -v`.

## Lệnh phát triển

- Test trong container dev: `docker compose exec app pytest -q`
- Lint: `docker compose exec app ruff check .`
- Format: `docker compose exec app ruff format .`
- Migration: `docker compose run --rm migrate`
- Tạo migration: `docker compose run --rm migrate alembic revision --autogenerate -m "ten thay doi"`

### Thư viện giao diện

HTMX và Alpine CSP được ghim phiên bản trong `package-lock.json`, vendoring vào `app/static/vendor` và phục vụ từ ứng dụng, không dùng CDN. Khi nâng phiên bản: chạy `npm ci`, `npm audit`, rồi `npm run vendor`; kiểm tra và commit cả lockfile lẫn các file trong `app/static/vendor`.

Hướng dẫn đăng nhập, khởi tạo Admin và xử lý mất TOTP: `docs/auth-usage.md`.
Hướng dẫn quản trị tài khoản: `docs/users-usage.md`.
Hướng dẫn quản lý mã hàng: `docs/product-usage.md`.
Hướng dẫn quản lý máy và cặp máy: `docs/assets-usage.md`.
Hướng dẫn quản lý nhân viên: `docs/employees-usage.md`.
Hướng dẫn quản lý mã lỗi: `docs/defect-codes-usage.md`.
Hướng dẫn quản lý lý do dừng máy: `docs/downtime-usage.md`.
Hướng dẫn quản lý kíp: `docs/shifts-usage.md`.
Hướng dẫn tạo và sửa PO: `docs/orders-usage.md`.
Hướng dẫn lập lịch sản xuất: `docs/schedules-usage.md`.
Hướng dẫn tạo yêu cầu xuất phôi: `docs/blank-requests-usage.md`.

Không chạy `docker compose down -v` trên môi trường có dữ liệu cần giữ.
