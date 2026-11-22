# Hàng sửa và QC lại

Danh sách hàng chờ sửa được tính từ NG sửa đã lưu trong QC theo lô, cộng NG sửa phát sinh ở các lượt QC lại.

Ghi mỗi lượt mang đi sửa theo đúng PO và lô, ngày, nhân viên mang/nhận sửa và số lượng. Hệ thống tự cấp mã phiếu ngắn, duy nhất dạng `SR-123`; ghi mã này lên giấy giao hàng để gửi cùng hàng. Tổng số mang đi sửa không được vượt số NG sửa đang chờ của lô.

Khi hàng quay lại, nhập mã phiếu sửa và số lượng nhận về để QC lại. Có thể QC một phần của phiếu; tổng số đã QC lại không được vượt số còn chờ QC của chính phiếu đó. Mỗi lượt phải có `OK + NG hủy + NG sửa = số đưa vào`. QC lại giữ liên kết tới cả phiếu sửa và lô gốc. NG sửa tạo lại số chờ sửa; NG hủy kết thúc vòng sửa; OK đi tiếp tới công đoạn sau.

API thao tác: `GET /repairs/queue`, `POST /repairs/jobs`, `POST /repairs/rechecks`. API QC lại nhận `repair_code` để liên kết đúng lượt mang đi sửa. POST yêu cầu phiên đăng nhập, quyền module sửa chữa và CSRF header `X-CSRF-Token` khớp cookie `mes_csrf`.

Màn hình người dùng tại `/repairs` hiện hỗ trợ công đoạn QC sản xuất: xem số chờ sửa theo PO và mã lô, ghi lượt mang đi sửa theo lô và QC lại theo mã phiếu. Giao diện chưa đưa quy trình Bavia vào phiên bản này.
