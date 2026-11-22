# Dịch vụ báo cáo

Các báo cáo đọc từ dữ liệu gốc, không lưu bộ đếm riêng. Bộ lọc hỗ trợ ngày, PO, cặp máy và người làm khi trường dữ liệu có áp dụng.

- `GET /reports`: giao diện xem tiến độ PO, sản lượng, NG, hàng sửa và OEE; có lọc dữ liệu, lọc ngày nhanh, mở dữ liệu sản lượng theo PO và xuất Excel.
- `GET /audit-log/view`: giao diện tra nhật ký theo ngày, loại dữ liệu và người thực hiện.

- `GET /reports/po-summary`: sản lượng, OK QC sản xuất, Bavia, thành phẩm đủ điều kiện, NG hủy, hàng chờ sửa, đã sửa, chờ QC lại và tiến độ PO.
- `GET /reports/production`: sản lượng SX và Bavia.
- `GET /reports/ng?kind=scrap|repair`: NG hủy/NG sửa của QC theo lô, QC Bavia hiện có và QC lại; QC theo lô hiển thị mã lỗi và máy ghi ở dòng chi tiết.
- `GET /reports/repairs`: lịch sử mang sửa và QC lại.
- `GET /reports/oee`: A và P theo dữ liệu cặp/kíp; Q và OEE chỉ tính khi gộp theo PO vì QC mới ghi theo lô, không thể phân bổ chính xác kết quả chất lượng cho từng máy/kíp. `group_by` hỗ trợ `day`, `month`, `order`, `product`, `pair`, `shift`.
- `GET /reports/export/{production|ng|repairs|oee|po-summary}`: xuất Excel theo cùng bộ lọc.
- `GET /audit-log`: nhật ký cho vai trò được cấp quyền `audit:view`.

OEE nhóm nhiều dòng bằng cách cộng số phút kế hoạch, dừng, chạy, giây lý tưởng và sản lượng rồi tính lại tỷ lệ; không lấy trung bình các tỷ lệ. Khi gộp PO, Q dùng OK lần đầu / số đã vào QC theo lô; chưa QC đủ các lô của PO thì Q/OEE chưa được kết luận. Cặp không ghi dừng được tính 0 phút dừng và vẫn có cờ `downtime_recorded` để theo dõi độ đầy đủ dữ liệu.
