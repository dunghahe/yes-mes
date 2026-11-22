# Hướng dẫn tạo và sửa PO

Kế hoạch mở **Danh sách PO** để tạo hoặc sửa PO.

Mỗi PO chứa một mã hàng, số lượng đặt, số lượng mỗi lô và loại công đoạn **Đầy đủ (SX và Bavia)**, **Chỉ sản xuất** hoặc **Chỉ Bavia**. Loại công đoạn được lưu ở PO; giá trị mặc định của mã hàng chỉ dùng làm gợi ý. Hệ thống tự tạo mã cho từng lô; lô cuối có thể ít hơn cỡ lô đã chọn.

Phải nhập đủ thông tin Kho nguyên vật liệu: mã nguyên vật liệu, mã bản vẽ, REV, chất liệu, kích cỡ phôi và ngày nhận ĐH. Số PO phải duy nhất, số lượng đặt là số nguyên dương. Khi PO đã có yêu cầu phôi, mã hàng và loại công đoạn bị khóa.

Tạo PO mở trong popup trên danh sách. Khi nhập Excel, dùng mẫu tải từ màn PO. Mỗi dòng là một PO; mã hàng phải trùng mã đang hoạt động, công đoạn ghi `FULL`, `SX_ONLY` hoặc `BAVIA_ONLY`, ngày theo `YYYY-MM-DD`. Hệ thống kiểm tra toàn bộ file trước; chỉ file không có lỗi mới được xác nhận nhập. Giới hạn file 10 MB và 5.000 dòng; bản xem trước hết hạn sau 15 phút. Không đổi số lượng PO hoặc cỡ lô sau khi đã lập lịch hoặc in biểu lô.
