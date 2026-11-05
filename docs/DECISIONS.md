# Quyết định

## 2026-11-05

- **Biểu in:** Chưa chốt khổ giấy, hướng in và số cặp tối đa. Người dùng sẽ gửi biểu mẫu giấy khi bắt đầu giai đoạn làm biểu in. Tạm giữ A4 dọc theo thiết kế.
- **Khu sản xuất:** Khu là khu sản xuất và được gắn với từng máy; khu không phải nhóm máy.
- **Quyền bổ sung:** Quyền tạo, sửa hoặc xóa được cấp thêm phải đi kèm quyền xem.
- **QC Bavia:** Số lượng đưa vào QC không được lớn hơn sản lượng đã ghi nhận.
- **Xóa dữ liệu:** Chỉ cho xóa khi chưa có dữ liệu phụ thuộc nào ảnh hưởng đến hệ thống. Nếu đã có dữ liệu phụ thuộc thì chặn xóa và giữ lại bản ghi.
- **Nhập báo cáo:** Không có nút “Lưu nháp”. Người nhập gửi báo cáo bằng một thao tác xác nhận; chỉ báo cáo xác nhận thành công mới được tính vào tổng quan PO và OEE.
- **TOTP:** Bắt buộc với tài khoản Admin.
- **Môi trường:** Production chạy trên Linux; môi trường phát triển dùng Windows, có thể qua WSL2.
- **Phiên đăng nhập:** Tự hết hạn sau 60 phút không có thao tác; thao tác hợp lệ sẽ làm mới thời gian chờ.
- **Giới hạn đăng nhập theo IP:** 100 lần đăng nhập sai trong 10 phút cho mỗi IP; đồng thời mỗi tài khoản khóa 10 phút sau 5 lần sai.
- **Admin đầu tiên:** Tạo bằng lệnh CLI tương tác chạy trực tiếp trên máy chủ, chỉ khi chưa từng có tài khoản Admin; không tạo tài khoản Admin qua đăng ký web.
- **Mật khẩu ban đầu/đặt lại:** Hệ thống sinh mật khẩu ngẫu nhiên và chỉ hiển thị một lần cho Admin chuyển tới người dùng qua kênh riêng; tài khoản phải đổi ở lần đăng nhập tiếp theo.
- **Admin cuối cùng:** Luôn giữ ít nhất một Admin đang hoạt động; chặn khóa hoặc hạ vai trò Admin đang hoạt động cuối cùng.
- **Xóa lịch sản xuất:** Được xóa mềm dòng lịch nếu yêu cầu phôi chưa được xác nhận giao. Yêu cầu phôi chưa giao vẫn giữ liên kết tới lịch đã xóa mềm. Nếu đã xác nhận giao thì chặn xóa lịch.

