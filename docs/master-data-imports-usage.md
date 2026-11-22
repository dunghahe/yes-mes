# Nhập danh mục từ Excel

Các màn **Máy và cặp máy**, **Nhân viên**, **Mã lỗi**, **Lý do dừng máy**, **Ca/kíp** có nút tải file mẫu và kiểm tra file Excel. Mỗi dòng là một bản ghi mới; không dùng Excel để cập nhật hoặc xóa dữ liệu đã có.

Quy trình: tải mẫu, điền dữ liệu, tải lên kiểm tra, sửa mọi lỗi được báo theo số dòng, rồi xác nhận nhập. File tối đa 10 MB và 5.000 dòng. Nếu có ít nhất một lỗi, hệ thống không ghi bất kỳ dòng nào. Khi xác nhận, các bản ghi được tạo trong một transaction và có audit log.

Mẫu **Mã lỗi** gồm Mã lỗi, Tên lỗi và Phát hiện tại (SX/BAVIA); đã bỏ cột Nhóm lỗi. Cần tải lại mẫu nếu file cũ vẫn có cột này.

Cặp máy chỉ tham chiếu hai máy đang hoạt động đã khai báo. Hãy nhập danh sách máy trước rồi mới nhập cặp máy. Danh sách tài khoản người dùng không hỗ trợ nhập Excel để tránh tạo hàng loạt thông tin đăng nhập hoặc quyền truy cập ngoài quy trình cấp mật khẩu an toàn.
