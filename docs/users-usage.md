# Hướng dẫn quản trị tài khoản

## Tạo tài khoản

1. Đăng nhập bằng tài khoản Admin và mở **Quản lý tài khoản**.
2. Chọn **Tạo tài khoản**, nhập tên đăng nhập, tên hiển thị và vai trò.
3. Sao chép mật khẩu tạm đang hiển thị. Mật khẩu này chỉ hiện một lần; gửi cho người dùng qua kênh riêng.
4. Người dùng đăng nhập bằng mật khẩu tạm và phải đổi mật khẩu ngay.

Không có đăng ký công khai. Admin đầu tiên được tạo bằng lệnh máy chủ theo hướng dẫn tại `docs/auth-usage.md`.

## Vai trò và quyền bổ sung

Vai trò cung cấp quyền cơ bản. Admin có thể cộng thêm quyền **Xem**, **Tạo**, **Sửa** hoặc **Xóa** theo từng mô-đun. Quyền Tạo/Sửa/Xóa yêu cầu bật **Xem**. Quyền bổ sung không làm mất quyền đã có từ vai trò.

Mỗi lần thay đổi quyền phải được lưu riêng cho mô-đun tương ứng. Nhật ký lưu người thực hiện và giá trị trước/sau.

## Khóa tài khoản và đặt lại mật khẩu

- Bỏ chọn **Tài khoản đang hoạt động** để khóa. Tài khoản không bị xóa nhằm giữ lịch sử.
- Không thể tự khóa tài khoản hoặc khóa/hạ vai trò Admin đang hoạt động cuối cùng.
- **Tạo mật khẩu tạm mới** thu hồi mọi phiên của người dùng. Mật khẩu mới chỉ hiện một lần và người dùng phải đổi ở lần đăng nhập tiếp theo.
- Chuyển mật khẩu tạm qua kênh riêng; không lưu vào nhật ký hay tin nhắn công khai.
