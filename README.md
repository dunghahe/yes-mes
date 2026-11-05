# Hệ thống nhập liệu sản lượng, NG và OEE

Ứng dụng mới theo thiết kế v1.2. Repo YGC cũ chỉ dùng tham khảo giao diện và quy trình; không dùng lại mô hình lô hoặc SQLite.

## Môi trường phát triển

Phát triển trong Ubuntu WSL2 trên Windows. Docker Desktop cần bật WSL2 engine và tích hợp với Ubuntu.

1. Tạo file cấu hình dev từ mẫu: `cp .env.example .env`.
2. Đặt mật khẩu dev riêng cho `POSTGRES_PASSWORD`, `MES_APP_PASSWORD` và `MES_MIGRATOR_PASSWORD`; cập nhật hai URL tương ứng.
3. Khởi động: `docker compose up --build`.
4. Chạy migration bằng service riêng: `docker compose run --rm migrate`.
5. Mở `http://localhost:8000`. PostgreSQL chỉ truy cập trong mạng nội bộ Docker; dùng `docker compose exec db psql -U mes_bootstrap -d mes` khi cần mở psql.
6. Dừng: `docker compose down`. Muốn xóa dữ liệu dev cục bộ: `docker compose down -v`.

## Lệnh phát triển

- Test trong container dev: `docker compose exec app pytest -q`
- Lint: `docker compose exec app ruff check .`
- Format: `docker compose exec app ruff format .`
- Migration: `docker compose run --rm migrate`
- Tạo migration: `docker compose run --rm migrate alembic revision --autogenerate -m "ten thay doi"`

Không chạy `docker compose down -v` trên môi trường có dữ liệu cần giữ.
