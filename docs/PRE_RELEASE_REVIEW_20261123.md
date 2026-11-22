# Rà soát trước phát hành · 23/11/2026

Nhánh làm việc: `codex/pre-release-audit`. Giữ nguyên các thay đổi dự án có sẵn; chưa commit/push, chưa thay dịch vụ chạy chính. Không sửa tài liệu thiết kế DOCX. Kết quả áp dụng cho phạm vi hiện tại, không đồng nghĩa mọi hạng mục nghiệp vụ tương lai đã hoàn thành.

## Lỗi đã sửa

| Vị trí | Vấn đề | Kết quả |
|---|---|---|
| `migrations/versions/20261122_36_lot_qc_summary.py`, `qc/service.py` | View tổng PO và tự đóng PO còn dùng QC theo cặp cũ | Dùng QC theo lô; fallback lịch sử chỉ khi PO chưa có QC lô; lưu QC cập nhật trạng thái và audit |
| `daily_reports/bavia_service.py` | FULL không nhận số OK QC lô làm đầu vào Bavia | Tính OK lần đầu và OK QC lại đúng công đoạn |
| `qc/service.py` | Sửa QC có thể giảm hàng sửa dưới số đã cấp phiếu hoặc giảm OK dưới số Bavia đã làm | Chặn trước khi ghi; giữ dữ liệu phụ thuộc |
| `daily_reports`, `qc`, `repairs` services | Thứ tự khóa PO/phiếu/lô không thống nhất; đối tượng trong Session có thể cũ sau khi chờ khóa | Khóa PO trước, đọc mới hàng đã khóa; kiểm tra version |
| `daily_reports/router.py`, `daily-report-form.js` | Lỗi lưu báo cáo có thể mất nội dung đang nhập | Trả lại payload và khôi phục ô nhập khi hiển thị lỗi |
| `daily_reports/router.py`, `bavia_router.py` | Có quyền tạo Bavia có thể chạm bản đã tồn tại | Bản đã tồn tại phải có quyền sửa, kể cả bỏ ID khi gửi form |
| `core/validation.py`, các JSON router | JSON sai hoặc validator có ValueError trong context có thể gây server error | JSON sai trả 400; lỗi dữ liệu trả 422 với chi tiết JSON an toàn |
| `form_templates/service.py` | Thay mẫu liên tiếp có thể xung đột bản đang dùng hoặc số version | Khóa transaction khi cấp version, flush bản cũ trước khi kích hoạt bản mới |
| `form_templates/service.py`, `reporting/router.py` | Dữ liệu bắt đầu bằng dấu `=` có thể trở thành công thức Excel | Ghi ô chuỗi tường minh khi điền biểu/xuất báo cáo |
| `reporting/dashboard.html`, CSS | Thanh tiến độ 0% hiển thị đầy vì inline style bị CSP chặn | Dùng thẻ progress, không cần nới CSP |
| CSS bố cục trang | Trang yêu cầu phôi tràn ngang trên viewport điện thoại | Grid thu được theo màn hình; bảng cuộn trong vùng riêng |
| `employee-autocomplete.js` | Chọn gợi ý xong danh sách tự mở lại | Đóng sau khi trả focus |
| `form-interactions.js` | Popup tự dựng không giữ Tab; có thể gửi lặp khi chờ phản hồi | Giữ vòng focus, trả focus khi đóng; khóa nút đang gửi |
| `warehouse/queue.html`, CSS | Ô PO/từ lô/số biểu lệch nhau | Nhãn cùng hàng, ô cùng hàng; PO đã chọn chỉ hiện số PO |
| Templates và `main.py` | Asset URL tuyệt đối có thể thành HTTP sau Tunnel; trang dữ liệu có thể bị cache | Asset URL tương đối; trang động `private, no-store` |
| `compose.production.yaml` | Compose hiện tại dành cho dev, có reload/bind mount | Bản production riêng, non-root, filesystem chỉ đọc, tmpfs, bỏ capabilities, log xoay vòng, không publish PostgreSQL |

## Kiểm chứng

- Bộ kiểm thử tổng thể: **143 passed**. Có các ca số mẫu QC → sửa → QC lại; tự đóng/mở PO; Bavia không vượt OK; không giảm sản lượng dưới số đã QC; stale version; giữ payload khi lưu sai; tạo không được sửa; upload mẫu liên tiếp; chuỗi công thức được giữ nguyên dạng chữ.
- Ma trận GET: 20 màn hình × 6 vai trò, kiểm 200/403 đúng quyền. Kiểm thêm JSON lỗi 400/422, header cache và CSP. Đây là kiểm server/render; không phải 120 phiên người dùng bấm mọi thao tác.
- Toàn bộ chuỗi Alembic: lên head36 → xuống base → lên head36 trên PostgreSQL sạch. Migration36 cũng đã lên/xuống/lên riêng và nâng trên bản restore có dữ liệu.
- Ruff: kiểm toàn bộ `app scripts migrations tests`; định dạng bằng Ruff. Kết quả cuối ghi trong nhật ký thực hiện, không bỏ qua lỗi bằng blanket ignore.
- Phép thử hai transaction QC đồng thời: sản lượng 100, hai lô mỗi lô 100; một lưu, một bị chặn; tổng QC cuối 100.
- pip-audit quét 37 dependency production đã khóa: chưa tìm thấy advisory đã biết tại lần kiểm tra này. Không bao gồm khẳng định về mọi package hệ điều hành hay mọi lỗ hổng chưa công bố.
- Image production không cài dev dependencies build được. In Excel → PDF → PNG bằng UID10001, root filesystem chỉ đọc: biểu sản lượng 1 trang, QC lô 1 trang.
- Container production riêng khởi động được; healthcheck nội bộ đạt; HTTP không có Access JWT trả403. Chưa xác minh hostname, audience và tunnel thật trên máy chủ của người dùng.
- Trình duyệt Edge: xem PO và popup, lịch tháng/ngày và form sửa, nhập sản lượng, QC tìm PO/lô, hàng sửa, báo cáo, kho và popup in. Không có error/warn trong log trình duyệt ở lượt cuối. Kiểm request popup ở390px; document width không vượt viewport. Giữ Tab trong popup và trả focus khi đóng đã kiểm.

## Backup và đối soát dữ liệu hiện tại

Backup: `backups/mes-pre-release-20261123.dump` (232104 bytes), từ DB dev đang dùng trên8010. Đây không phải xác nhận backup một server sản xuất khác.

Đã restore vào DB riêng và nâng lên head36. Số hàng nguồn/restore khớp: 4 PO, 5 yêu cầu, 36 lô, 0 kết quả QC lô, 2 phiếu sửa. Tổng PO từ service và SQL view không lệch; không có số dư sửa âm. Runtime có SELECT/INSERT audit, không có UPDATE/DELETE audit.

Trong dữ liệu này có **0 nhân viên QC hoạt động** và **2 phiếu sửa cũ chờ QC chưa gắn lô**. Cần khai báo người QC; dữ liệu sửa cũ phải có phương án người dùng xác nhận trước khi tiếp tục chuyển sang luồng theo lô. Không tự suy đoán hoặc xóa lịch sử.

## Điều kiện còn lại trước chạy thật

1. Mẫu sản lượng chỉ có6 dòng cặp máy, hệ thống cho khai báo tối đa40; yêu cầu hơn6 cặp đang bị chặn in để không mất dữ liệu. Chưa tự đặt giới hạn mới hoặc tự thiết kế nhiều trang khi chưa chốt.
2. In A4 và quét QR trên thiết bị thật; kiểm chữ dài và vùng ghi tay. Kiểm PDF trong container chưa thay thế nghiệm thu máy in.
3. Chốt cách xử lý2 phiếu sửa cũ nếu cần tiếp tục chúng. Kiểm lại các lịch trùng từ giai đoạn thử; không tự gộp/xóa vì có thể là lịch độc lập hợp lệ.
4. QC Bavia và nhập kho thành phẩm vẫn được hoãn theo quyết định phạm vi. FULL/BAVIA_ONLY không được coi sản lượng Bavia là thành phẩm đã QC; tự đóng PO vẫn dựa trên OK công đoạn cuối.
5. Điền secret/Access thực, kiểm đăng nhập TOTP sau restore, cấu hình backup mã hóa ngoài máy và thử truy cập hostname thật.
6. OEE A/P theo cặp/kíp; Q/OEE theo PO khi dữ liệu QC đủ điều kiện. Không suy ra số OK theo máy từ QC lô. Chưa có phép thử tải dài trên cấu hình máy chủ thật.

## Giới hạn kiểm tra bảo mật

Đã đọc mã, chạy các kiểm thử bảo mật/phân quyền hiện có và pip-audit. Công cụ deep scan của plugin không khởi động được do từ chối đường dẫn lưu output trên Windows (`Scan output directory can be replaced by another user`, tại `C:\Users`). Không đổi ACL hệ thống để bỏ qua bảo vệ; không có kết quả deep scan để tuyên bố đạt.

Đối chiếu giao diện theo [Web Interface Guidelines](https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md); các lỗi tràn nội dung, focus, inline style/CSP và nhãn đã được kiểm theo phạm vi trên.

Hướng dẫn máy chủ: `docs/deploy-linux.md`. Image ứng viên được build riêng; chưa tự chuyển tag/dịch vụ chạy chính.

## Bản đóng gói đã kiểm tra

- Tag local: `ygc-mes:release-audit-20261123`.
- Image ID: `sha256:40979e212df8d3301055b91d11049a1f6de8e94222fba7f4d5c5af746541c915`.
- Image cuối: healthcheck đạt, thiếu Access JWT trả403, không có pytest, UID10001, in mỗi loại biểu1 trang trên root filesystem chỉ đọc.
- Đã thử `compose.production.yaml` với PostgreSQL volume trống ở project Docker riêng: script init tạo runtime/migrator không có SUPERUSER/CREATEDB; migration từ đầu đến36 thành công bằng image production.
- Sau thay URL asset sang tương đối, chạy lại toàn bộ ma trận màn hình6 vai trò:6 ca đạt. Lượt Ruff cuối: `All checks passed!`.
- CLI đối soát trên bản restore ở chế độ chạy thử:0 PO cần đổi trạng thái, không lưu thay đổi.
- Container và volume Docker dùng riêng cho diễn tập được dọn sau kiểm tra; backup dev được giữ trong thư mục backups.
