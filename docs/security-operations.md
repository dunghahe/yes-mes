# Vận hành khóa mã hóa TOTP

## Tạo khóa ban đầu

Tạo khóa Fernet trong môi trường tin cậy:

```sh
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Đặt giá trị vào `TOTP_ENCRYPTION_KEYS` trong secret store hoặc file môi trường được bảo vệ. Không commit giá trị này, không đưa vào log. Sao lưu khóa riêng, mã hóa và cất ngoài máy chủ; nếu mất khóa, không thể giải mã bí mật TOTP hiện có.

## Xoay khóa

1. Tạo khóa mới, sao lưu an toàn khóa mới và cũ.
2. Đặt `TOTP_ENCRYPTION_KEYS` thành `khóa_mới,khóa_cũ` (khóa đầu danh sách dùng để mã hóa mới).
3. Khởi động lại ứng dụng và chạy `docker compose exec app python -m scripts.rotate_totp_key` trên máy chủ.
4. Kiểm tra lệnh báo số tài khoản đã xử lý và xác nhận đăng nhập TOTP hoạt động.
5. Bỏ khóa cũ khỏi cấu hình, khởi động lại ứng dụng, rồi kiểm tra TOTP lần nữa.
6. Chỉ hủy bản sao khóa cũ theo quy trình lưu trữ bí mật sau khi backup mã hóa mới đã được xác nhận.

Lệnh xoay ghi audit cho từng tài khoản nhưng không ghi bí mật TOTP hoặc giá trị khóa vào audit.
