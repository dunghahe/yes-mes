# QC theo lô

Mở **QC theo lô**. Bên trái, gõ PO để nhận gợi ý rồi tìm danh sách lô đã in; hoặc quét/nhập mã lô để nhận gợi ý và mở trực tiếp. Danh sách cho biết lô **Chưa QC** hay **Đã QC**. Chọn lô để nhập ở vùng bên phải.

- Chọn ngày, kíp và người QC.
- Nhập OK và tổng NG. Tổng hai số phải bằng số lượng lô.
- Khi có NG, thêm các dòng theo nhóm số lượng: dạng lỗi, máy gây lỗi, kết quả hủy/sửa và số lượng. Tổng số lượng các dòng phải bằng tổng NG phía trên. Không nhập riêng từng sản phẩm.
- Danh sách dạng lỗi hiện dùng chung cho các mã hàng và được khai báo một lần trong phần quản trị danh mục lỗi.
- Chỉ lưu khi sản lượng đã xác nhận của PO đủ đáp ứng số QC lũy kế, gồm cả lô đang lưu.
- Chọn **Lưu kết quả QC**. Có thể mở lại lô để xem hoặc cập nhật nếu có quyền sửa; mọi lần lưu được ghi nhật ký.

Kho NVL in phiếu ở hàng đợi bằng cách chọn PO, khoảng lô và các phiếu cần in. Có thể in tối đa 100 lô một lần, không cần chờ QC nhập. Mỗi lô là một trang HTML A4 có QR/mã lô; trình duyệt mở hộp thoại in ngay trên trang hiện tại.

QC theo lô không thay đổi cách nhập sản lượng theo ngày/kíp/cặp máy. Khi nhập QC, không nhập lại sản lượng. Bavia chưa thuộc phạm vi lát này.

Quyền màn QC: `qc:view` để tra cứu; `qc:create` để lưu lần đầu; `qc:edit` để cập nhật kết quả đã lưu. Các route kiểm quyền ở server.
