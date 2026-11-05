# Hướng dẫn đăng nhập và tài khoản

## Tạo Admin đầu tiên

Sau khi PostgreSQL sẵn sàng và migration đã chạy, chạy lệnh ngay trên máy chủ:

```sh
docker compose exec app python -m scripts.bootstrap_admin
```

Lệnh hỏi tên đăng nhập, tên hiển thị và mật khẩu tương tác; mật khẩu không hiện trên màn hình. Lệnh chỉ chạy nếu chưa từng có tài khoản Admin (kể cả tài khoản đã xóa mềm). Không tạo Admin qua form web.

## Đăng nhập lần đầu

1. Đăng nhập bằng thông tin Admin vừa tạo.
2. Đổi mật khẩu tạm.
3. Thiết lập TOTP bằng cách quét mã QR trong ứng dụng xác thực hoặc nhập khóa thủ công.
4. Nhập mã 6 chữ số để xác nhận. Lưu 10 mã dự phòng ở nơi an toàn; mỗi mã chỉ dùng một lần.

Tài khoản khác cũng phải đổi mật khẩu ở lần đăng nhập đầu hoặc sau khi Admin đặt lại mật khẩu. Mật khẩu hết hạn sau ba tháng. Phiên hết hạn sau 60 phút không thao tác; thao tác hợp lệ làm mới thời gian.

## Khóa tài khoản và giới hạn IP

Tài khoản khóa 10 phút sau 5 lần nhập sai. Mỗi IP bị giới hạn 100 lần đăng nhập sai trong 10 phút. Các bộ đếm được lưu trong PostgreSQL để dùng chung giữa nhiều worker và không mất khi ứng dụng khởi động lại.

## Mất thiết bị TOTP

Nếu Admin mất cả thiết bị và mã dự phòng, người có quyền vận hành máy chủ chạy:

```sh
docker compose exec app python -m scripts.reset_admin_totp
```

Lệnh yêu cầu xác nhận trực tiếp, thu hồi tất cả phiên và bắt Admin đổi mật khẩu rồi thiết lập TOTP mới.

Giữ khóa `TOTP_ENCRYPTION_KEYS` bên ngoài git và sao lưu mã hóa. Xem cách xoay khóa tại `docs/security-operations.md`.
