# Báo cáo sản lượng và QC Bavia

Ghi sản lượng Bavia theo PO, ngày, kíp và người làm. Có thể cập nhật cùng tổ hợp nếu gửi đúng `version`. Với PO FULL, tổng Bavia không được vượt số OK đã hoàn tất QC sản xuất, gồm cả OK sau QC lại. Với PO BAVIA_ONLY, cần có xác nhận giao phôi. Kho tạm chưa thu thập số thực giao nên nếu có phiếu giao chưa có số lượng, không áp giới hạn dựa trên tổng phôi; không coi số chưa biết là 0. Khi toàn bộ phiếu có số thực giao thì tổng Bavia vẫn không được vượt tổng đó.

QC Bavia lấy sản lượng Bavia làm số lượng vào QC theo nguyên tắc 1:1; chỉ ghi NG hủy và NG sửa, OK được suy ra. Mỗi báo cáo Bavia có một kết quả QC; không sửa sản lượng sau khi đã có QC. QC Bavia đầy đủ là nguồn NG sửa cho công đoạn `QC_BAVIA`.

Form nhập Bavia nằm trong mục **Sản lượng**. PO FULL chuyển tab từ Sản xuất sang Bavia; PO BAVIA_ONLY mở form Bavia bằng mã yêu cầu phôi sau khi Kho NVL xác nhận giao. Có thể sửa dòng đã nhập nếu có quyền sửa; hệ thống cập nhật đúng mã báo cáo và kiểm tra phiên bản. Sau khi đã có QC Bavia, không cho sửa thông tin/sản lượng của dòng đó.

API: `GET /bavia-reports`, `POST /bavia-reports`, `POST /bavia-reports/{id}/qc`. POST yêu cầu CSRF và quyền tương ứng.
