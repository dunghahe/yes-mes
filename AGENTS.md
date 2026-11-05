# Hệ thống nhập liệu sản lượng NG và OEE

## Nguồn chuẩn và thay đổi
- Nguồn thiết kế mới nhất trong repo là `docs/Thiet_ke_chi_tiet_v1_2.docx` và sơ đồ `docs/he_thong_nhap_lieu_san_luong (3).drawio`; repo cũ `dunghahe/nhaplieu_YGC` chỉ dùng tham khảo giao diện/nghiệp vụ, không bê schema hoặc luồng lô sang.
- Không sửa tài liệu thiết kế. Nếu mã và thiết kế mâu thuẫn, hoặc thiết kế chưa nói rõ, ghi đề xuất vào `docs/OPEN_QUESTIONS.md`, làm phần không bị ảnh hưởng rồi dừng tại điểm bị chặn.
- Quyết định người dùng chốt ghi vào `docs/DECISIONS.md` với ngày. Không tự chốt mục còn mở.
- Không làm giai đoạn sau khi giai đoạn trước chưa nghiệm thu. Mỗi lát nhỏ (một use case/màn hình) làm trên nhánh riêng, một diff để review.

## Thứ tự mỗi lát việc
1. Migration PostgreSQL lên/xuống.
2. Service chứa toàn bộ quy tắc nghiệp vụ; router chỉ nhận request và gọi service.
3. Màn hình Jinja2/HTMX/Alpine.js.
4. Kiểm thử ràng buộc Chặn/Cảnh báo, phân quyền, nhật ký và các số mẫu tính tay.
5. Tài liệu hướng dẫn và cập nhật `docs/DECISIONS.md` nếu có quyết định mới.

## Stack và môi trường
- Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16. Không dùng SQLite.
- Giao diện server-render bằng Jinja2 + HTMX + Alpine.js, CSS tự viết; hỗ trợ dark/light. Tự lưu JS/font trong repo, không dùng CDN hoặc script nội tuyến; Alpine dùng `@alpinejs/csp`, HTMX tắt eval.
- In A4 bằng HTML/CSS và QR; Excel bằng openpyxl. Giao diện, nhãn và lỗi bằng tiếng Việt; thời gian `Asia/Ho_Chi_Minh`.
- Dev trên Windows qua WSL2/Docker Compose; production chạy Docker Compose trên Linux, truy cập từ xa qua Cloudflare Tunnel/Access theo `docs/DECISIONS.md` và `docs/security-operations.md`.

## Cấu trúc dự kiến
```text
app/
  main.py
  core/        config, db, security, audit, permissions, csrf
  modules/     auth, users, master, orders, schedules, blank_requests,
               daily_reports, qc, repairs, reporting
               (mỗi module: models.py, schemas.py, service.py, router.py, templates/)
  templates/   base, components dùng chung
  static/      css, js
migrations/    Alembic, mỗi migration một thay đổi, có hàm lùi
tests/         unit/, services/, views/, e2e/
docs/
```
- Tên bảng/cột/biến/hàm tiếng Anh. PK `id` bigint identity. Enum text + CHECK; số lượng integer + CHECK >= 0; ngày giờ timestamptz.
- Mọi bảng nghiệp vụ có `created_at`, `created_by`, `updated_at`, `updated_by`, `deleted_at`; xóa mềm. Audit ghi old/new, actor, lý do. Tài khoản ứng dụng không có UPDATE/DELETE trên `audit_log`.
- Mã duy nhất có xóa mềm dùng partial unique index `WHERE deleted_at IS NULL`. Bảng có cập nhật đồng thời có `version`.
- Ràng buộc tổng <= kiểm trong transaction có khóa dòng cha thích hợp (`SELECT ... FOR UPDATE`). Không sửa/xóa bản ghi nếu có dữ liệu phụ thuộc phía sau.
- Mỗi mã hàng có một cycle time giây/con; snapshot lưu ở từng dòng báo cáo. View PO/OEE tính từ dữ liệu gốc, không lưu bộ đếm riêng.

## Quy tắc nghiệp vụ đã chốt
- Một PO một mã hàng, không quản lý lô. `process_type` bắt buộc: FULL, SX_ONLY, BAVIA_ONLY. Thông tin kho nguyên vật liệu của PO đều bắt buộc.
- Lịch không gắn nhóm máy. Kỹ thuật chọn nhóm/cặp/người làm khi tạo yêu cầu phôi. QC theo cặp × ngày × kíp.
- Khu là khu sản xuất và gắn với từng máy, không phải nhóm máy.
- NG hủy tính ngay; NG chờ sửa tích theo PO/công đoạn; QC lại quay về đúng công đoạn.
- QC Bavia: số đưa vào không được lớn hơn sản lượng đã ghi nhận. Ràng buộc tổng <= phải an toàn khi lưu đồng thời.
- Không có nút “Lưu nháp” trên màn hình nhập báo cáo. Một thao tác xác nhận lưu báo cáo; chỉ báo cáo đã xác nhận được tính vào tổng quan PO/OEE.
- Giấy không ghi dừng: mặc định phút dừng = 0; `downtime_recorded` cho biết giấy có ghi dừng không. OEE A phải hiển thị tỷ lệ kíp không ghi dừng.
- OEE = A × P × Q; Q dùng OK lần đầu; tính theo cặp × kíp. Khi gộp, cộng tử số và mẫu số, không lấy trung bình tỷ lệ.
- PO tự đóng theo `settings.po_auto_close_pct` (mặc định 100%) dựa trên OK công đoạn cuối, kể cả OK sau QC lại. Tự mở lại khi số OK tụt dưới ngưỡng, trừ PO đóng tay. Mọi chuyển trạng thái có audit log.
- Quyền cấp thêm theo người chỉ cộng vào quyền vai trò; quyền tạo/sửa/xóa cấp thêm phải đi kèm quyền xem. Mọi route kiểm quyền ở server.
- Chỉ xóa khi không có dữ liệu phụ thuộc. Nếu có dữ liệu phụ thuộc thì chặn xóa; không cascade xóa lịch sử.
- TOTP bắt buộc cho Admin. Chỉ Admin tạo tài khoản. Bcrypt; giới hạn sai mật khẩu, rate limit theo IP; cookie Secure/HttpOnly/SameSite; CSRF mọi form HTMX; autoescape Jinja; không ghép SQL; bí mật ngoài mã nguồn.

## Bảo mật và vận hành
- Production Linux; app sau Cloudflare Tunnel/Access, không mở PostgreSQL ra ngoài. Khi dùng Access, kiểm chữ ký/thời hạn/audience JWT tại app.
- Hai DB account: migration và runtime; runtime quyền tối thiểu. TOTP secret mã hóa, có quy trình xoay khóa.
- Backup `pg_dump` hằng ngày, giữ 14 ngày, thêm bản mã hóa ngoài máy chủ; mỗi quý thử khôi phục sang máy khác.
- Khóa phiên bản thư viện bằng lock file; `pip-audit` chạy định kỳ/CI.
- Trước khi hoàn tất mỗi lát: migration chạy lên/xuống trên PostgreSQL sạch; test từng ràng buộc và quyền đúng/sai; kiểm audit; `ruff` sạch và `pytest` đạt. Không tuyên bố kiểm tra đạt nếu chưa chạy được.

## Các điểm còn mở
- Xem `docs/OPEN_QUESTIONS.md`. Biểu mẫu giấy chờ người dùng gửi khi bắt đầu lát in. Không suy diễn quyết định chưa chốt.
