# Vai trò và màn hình được truy cập

Menu chỉ hiện phân hệ mà tài khoản có quyền xem hoặc thao tác tương ứng. Mỗi route cũng kiểm tra quyền ở server; ẩn menu không thay thế kiểm tra quyền.

| Vai trò | Màn hình chính |
|---|---|
| Admin | Toàn bộ phân hệ, cấu hình và quản trị tài khoản. |
| Kế hoạch | PO (xem/tạo/sửa), Lịch sản xuất (xem/tạo/sửa; tạo bằng popup), Danh mục dùng chung (chỉ xem), Báo cáo. |
| Kỹ thuật | PO (xem), Lịch sản xuất (xem), Yêu cầu phôi (xem/tạo), Danh mục dùng chung (chỉ xem), Báo cáo. |
| Kho NVL | PO (xem), Lịch sản xuất (xem), Yêu cầu phôi (xem), Kho NVL (in biểu và xác nhận giao), Danh mục dùng chung (chỉ xem), Báo cáo. |
| Nhập liệu | PO và Lịch sản xuất (xem), Yêu cầu phôi (xem/sửa theo quy tắc), Sản lượng (nhập/sửa), QC theo lô (nhập/sửa), Hàng sửa (ghi nhận mang đi và QC lại), Danh mục dùng chung (chỉ xem), Báo cáo. |
| Quản lý | PO, Lịch sản xuất, Sản lượng, QC theo lô, Hàng sửa, Danh mục dùng chung và Báo cáo (chỉ xem); Nhật ký. |

QC sản xuất có màn riêng **QC theo lô**. Kho NVL in biểu theo lô trong hàng đợi Kho NVL; nhập QC và sửa kết quả vẫn cần quyền `qc:create` hoặc `qc:edit`. Màn **Danh mục dùng chung** chỉ đọc cho các vai trò có quyền `master:view`; màn **Quản trị** và thao tác thêm/sửa/ngừng dùng danh mục chỉ dành cho Admin.

Quyền cấp riêng cho một tài khoản chỉ bổ sung quyền so với vai trò, không thu hồi quyền mặc định của vai trò. Ví dụ, cấp quyền xem không làm mất quyền tạo PO sẵn có của vai trò Kế hoạch.
