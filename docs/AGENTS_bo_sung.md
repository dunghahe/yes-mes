# Bổ sung cho AGENTS.md

> Tài liệu này ghi lại các yêu cầu bổ sung. Khi nội dung [CHỜ CHỐT] cũ mâu thuẫn với `AGENTS.md`, `docs/DECISIONS.md` hoặc `docs/OPEN_QUESTIONS.md` hiện hành, dùng các quyết định mới hơn làm chuẩn.

Dán các mục dưới đây vào AGENTS.md. Mục nào có dấu [CHỜ CHỐT] thì chưa được tự làm, ghi vào `docs/OPEN_QUESTIONS.md` và hỏi lại.

## Tài liệu trong repo
- Nguồn chuẩn nằm trong `docs/`: `Thiet_ke_chi_tiet_v1_2.docx`, `he_thong_nhap_lieu_san_luong (3).drawio`, `OPEN_QUESTIONS.md`, `DECISIONS.md`.
- Không sửa tài liệu thiết kế. Khi mã nguồn và tài liệu mâu thuẫn, hoặc gặp điều tài liệu chưa nói: ghi câu hỏi vào `docs/OPEN_QUESTIONS.md` (kèm mục tài liệu liên quan và đề xuất của bạn), làm phần không bị ảnh hưởng, rồi dừng ở chỗ bị chặn. Không đoán.
- Quyết định mới do người dùng chốt thì ghi vào `docs/DECISIONS.md` (ngày, nội dung).

## Lệnh thường dùng (chỉnh cho đúng repo thực tế)
```
docker compose up -d db           # PostgreSQL 16 cho dev
alembic upgrade head              # áp migration
alembic downgrade -1              # kiểm tra migration lùi được
pytest -q                         # toàn bộ test
pytest tests/services -q          # test ràng buộc nghiệp vụ
ruff check . && ruff format .     # lint và format
uvicorn app.main:app --reload --host 127.0.0.1
pip-audit                         # quét lỗ hổng thư viện
```

## Cấu trúc thư mục
```
app/
  main.py
  core/        config, db, security, audit, permissions, csrf
  modules/     auth, users, master, orders, schedules, blank_requests,
               daily_reports, qc, repairs, reporting
               (mỗi module: models.py, schemas.py, service.py, router.py, templates/)
  templates/   base, components dùng chung (bảng, form, thông báo)
  static/      css, js (HTMX, Alpine bản CSP, tự lưu trong repo)
migrations/    Alembic, mỗi migration một thay đổi, có hàm lùi
tests/         unit/, services/, views/ (số mẫu tính tay), e2e/
docs/
```
- Tên bảng, cột, biến, hàm bằng tiếng Anh. Giao diện, thông báo lỗi, nhãn bằng tiếng Việt.
- Router chỉ nhận request và gọi service. Mọi ràng buộc nghiệp vụ nằm trong `service.py`, không nằm trong router hay template.

## Định nghĩa "xong" cho mỗi lát việc (một usecase hoặc một màn hình)
1. Migration lên và lùi chạy được trên PostgreSQL sạch.
2. Có test cho từng ràng buộc "Chặn" và "Cảnh báo" của usecase đó, và test phân quyền (vai trò đúng được, vai trò sai bị từ chối ở server).
3. Mọi thêm, sửa, xóa của lát đó có dòng trong `audit_log` (test kiểm).
4. `ruff` sạch, `pytest` đạt, không cảnh báo mới.
5. Giao diện: lỗi hiện cạnh trường, dùng được bằng bàn phím.
6. Cập nhật `docs/DECISIONS.md` nếu có quyết định mới. Không sửa tài liệu thiết kế.
Mỗi lát nhỏ (một usecase), một nhánh, một diff để review.

## Đồng thời và toàn vẹn dữ liệu
- Tối đa khoảng 20 người dùng cùng lúc. Các ràng buộc dạng "tổng ≤" (mục 4.4) phải kiểm trong một transaction có khóa dòng cha (`SELECT ... FOR UPDATE` trên PO, `daily_report_pairs` hoặc cặp (PO, công đoạn) tương ứng), để hai người lưu cùng lúc không làm tổng vượt số cho phép.
- Mọi bảng có thể bị hai người sửa cùng lúc có cột `version`. Lưu bản cũ thì báo lỗi bằng tiếng Việt và cho tải lại, không ghi đè.
- Xóa mềm: các mã duy nhất (`po_no`, `code`, `req_no`, `username`) dùng chỉ mục duy nhất một phần `where deleted_at is null`.
- Ngày của kíp là ngày bắt đầu kíp. Kíp qua nửa đêm: giờ kết thúc thuộc ngày hôm sau nhưng `report_date` vẫn là ngày bắt đầu. Có test cho kíp qua nửa đêm.
- Script `scripts/seed_demo.py` nạp dữ liệu mẫu có đáp án tính tay (một PO FULL, một SX_ONLY, một BAVIA_ONLY, có NG hủy, NG sửa, QC lại). Test view `v_po_summary` và `v_oee_pair_shift` đối chiếu với số này.

## OEE khi giấy không ghi dừng máy
- Giấy không ghi dừng máy nghĩa là coi kíp đó máy không dừng (phút dừng 0). Không có nghĩa máy không bao giờ dừng: khi giấy có ghi dừng thì dùng số đã ghi.
- A = (thời gian kế hoạch − phút dừng đã ghi) ÷ thời gian kế hoạch. `downtime_recorded` là cờ thông tin cho biết giấy kíp đó có ghi dừng hay không.
- View `v_oee_pair_shift` trả thêm cột `downtime_recorded`. Báo cáo OEE hiện kèm tỷ lệ kíp không ghi dừng máy để người đọc biết mức tin cậy của A.
- Ô phút dừng trên Biểu sản xuất là tùy chọn, chỉ ghi khi có dừng.

## PO tự đóng và mở lại (đã chốt)
- Ngưỡng nằm trong `settings` (`po_auto_close_pct`, mặc định 100). Thành phẩm là số OK ở công đoạn cuối, kể cả OK sau QC lại.
- PO tự mở lại khi số OK tụt dưới ngưỡng sau khi sửa dữ liệu. PO do người dùng đóng tay (`orders.closed_manually = true`) thì không tự mở lại.
- Mọi lần chuyển trạng thái của PO ghi `audit_log`.

## Phân quyền thêm theo từng người (đã chốt)
- Admin cấp thêm quyền cho từng người khi cần, bảng `user_permissions` (user_id, module, can_view, can_create, can_edit, can_delete). Quyền hiệu lực = quyền theo vai trò cộng quyền cấp thêm. Chỉ cộng thêm, không bớt quyền của vai trò.
- Danh sách module là hằng số trong mã nguồn: master, orders, schedules, blank_requests, daily_reports, qc, repairs, reports, audit. Mọi route kiểm quyền hiệu lực ở server.
- Chỉ Admin được cấp, sửa, thu hồi quyền; mọi thay đổi ghi `audit_log`.

## Bảo mật bổ sung
- CSP: dùng bản `@alpinejs/csp`, tắt eval của HTMX (`htmx.config.allowEval = false`), tự lưu mọi thư viện JS và font trong repo, không tải từ CDN, không dùng script nội tuyến.
- Nếu dùng Cloudflare Access, kiểm tra thêm token `Cf-Access-Jwt-Assertion` ở app (chữ ký, thời hạn, audience) làm lớp thứ hai.
- Database: hai tài khoản riêng, một để chạy migration, một cho ứng dụng. Tài khoản ứng dụng không có quyền UPDATE, DELETE trên `audit_log`.
- `totp_secret` mã hóa bằng khóa trong biến môi trường (ví dụ Fernet), ghi rõ cách xoay khóa trong `docs/`.
- Giới hạn tốc độ đăng nhập lưu trong database (bảng đếm), không lưu trong bộ nhớ từng tiến trình.
- Ghi nhật ký đăng nhập sai (không ghi mật khẩu). Không đưa mật khẩu, token, mã TOTP vào log.
- Khóa phiên bản thư viện bằng file lock, `pip-audit` chạy trong CI hoặc trước mỗi lần phát hành.
- Backup: mỗi quý khôi phục thử một bản vào máy khác và kiểm số liệu.

## Triển khai (đã chốt)
- Production chạy Docker Compose trên Linux, dùng PostgreSQL và Cloudflare Tunnel/Access; môi trường phát triển dùng Windows/WSL2.
- Ứng dụng kiểm chữ ký và claims của `Cf-Access-Jwt-Assertion` theo team domain và AUD tag đã cấu hình.
- Backup hằng ngày, lưu 14 ngày, mã hóa bản sao off-host và ghi kết quả vào log; hướng dẫn ở `docs/backup-operations.md`.

## Quyết định đã chốt thêm khi cập nhật v1.2
- Mã lỗi không gắn máy gợi ý (không có `defect_codes.default_machine_id`). QC vẫn chọn máy gây lỗi (tùy chọn) ở từng dòng NG.
- Bảng `orders` không có ngày giao (`due_date`).
- Tài liệu v1.2 đã khớp AGENTS.md về PostgreSQL cho cả dev, Cloudflare Tunnel với Access và TOTP cho Admin.

## Còn mở (hỏi người dùng, không tự quyết)
- Khổ giấy, hướng in biểu và số cặp tối đa trên một biểu; chốt theo mẫu giấy người dùng sẽ gửi.

