# Câu hỏi còn mở

## 2026-11-23 · Trước chuyển máy chủ

- Bản backup dev hiện có2 phiếu sửa chờ QC chưa gắn lô. Cần người dùng xác nhận phiếu/lô đối chiếu hoặc cách kết thúc luồng cũ; không tự gán lô hay xóa lịch sử.
- Chưa có nhân viên QC hoạt động trong dữ liệu đang thử. Cần khai báo trước khi nhập QC/QC lại.
- Giới hạn6 dòng máy trên biểu so với tối đa40 cặp vẫn chưa chốt. Giữ chặn in vượt mẫu; chưa tự đổi quy tắc nghiệp vụ.

## 2026-11-19

1. **Biểu QC theo lô:** Đã dựng biểu HTML/CSS một trang theo ảnh, không có PDF gốc. Cần in thử A4 trên máy thực tế để xác nhận vùng ghi tay và tỷ lệ.
2. **Dữ liệu QC/hàng sửa cũ:** Những kết quả QC trước khi có mã lô không thể gắn ngược chính xác vào từng lô/máy. Cần xác nhận PO nào còn dữ liệu cũ cần tiếp tục theo dõi sửa để chọn cách xử lý mà không suy đoán lô.
3. **Biểu sản lượng hiện tại:** Còn giới hạn 6 dòng cặp máy trong mẫu trong khi hệ thống hỗ trợ tối đa 40 cặp, và cách ghi nhiều lý do dừng trên giấy chưa chốt.
## 2026-11-11

1. **Số cặp trên biểu:** Mẫu Excel có 6 dòng cặp máy, trong khi yêu cầu phôi hiện cho phép tối đa 40 cặp. Bản in phần mềm chặn in nếu có hơn 6 cặp để không làm rơi dữ liệu; cần chốt giới hạn tạo yêu cầu hoặc thiết kế mẫu nhiều trang.
2. **Nhiều lý do dừng máy:** Hướng dẫn trên biểu sản lượng yêu cầu ghi thêm dòng nếu có nhiều lý do, nhưng bảng hiện chưa có dòng trống bổ sung. Cần chốt cách ghi.
3. **Khổ và tỷ lệ in:** Cần in thử biểu cũ trên máy thực tế để xác nhận cỡ chữ và ô ghi tay dùng được.

## 2026-11-12

1. **Số cặp trên biểu:** Mẫu có 6 dòng. Nếu yêu cầu chọn hơn 6 cặp, ứng dụng chặn in để không làm rơi dữ liệu; cần chốt có giới hạn tạo yêu cầu ở 6 cặp hay cần thiết kế mẫu nhiều trang.
