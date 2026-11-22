# Hướng dẫn tạo yêu cầu xuất phôi

Kỹ thuật chọn **Tạo yêu cầu phôi** từ một dòng lịch, hoặc mở màn hình **Yêu cầu xuất phôi** và chọn dòng lịch. PO, mã hàng, ngày và kíp được lấy từ lịch.

Với PO sản xuất, chọn một hoặc nhiều cặp máy đang hoạt động và đúng một người làm cho từng cặp. Với PO **BAVIA_ONLY**, yêu cầu lấy ngày/kíp từ lịch và không cần chọn máy hoặc người làm máy. Người yêu cầu không nhập số lượng phôi; Kho NVL tự cân đối theo PO và tồn kho. Khi gửi, hệ thống cấp mã `YC-yyMMdd-nn` và đưa yêu cầu sang trạng thái **Chờ Kho NVL giao**.

Danh sách yêu cầu hiển thị cho các vai trò được cấp quyền xem. Yêu cầu sản xuất lưu người làm trên từng cặp máy để biểu sản xuất có thể điền đúng theo dòng; yêu cầu BAVIA_ONLY không có phân công máy. Các thay đổi được ghi nhật ký.

Nhập liệu có thể mở, sửa hoặc hủy yêu cầu đang **Chờ Kho NVL giao**. Mỗi lần sửa hoặc hủy phải nhập lý do; hủy sẽ chuyển trạng thái sang **Đã hủy**. Sau khi Kho NVL xác nhận giao, yêu cầu bị khóa với Nhập liệu; chỉ Admin được sửa.

Kho NVL mở **Hàng chờ Kho NVL** để xem các yêu cầu đang chờ giao. Danh sách tự làm mới mỗi 15 giây. Biểu sản xuất được in từ từng yêu cầu; biểu QC theo lô được chọn và in riêng từ nút **In biểu QC theo lô**, kể cả trước khi có kết quả QC. Admin thay mẫu Excel tại **Quản lý mẫu biểu Excel**. Mẫu hiện dùng hai sheet: **Sản lượng** và **QC theo lô**; sheet QC cũ đã bỏ.

Hàng chờ hiển thị **Mã NVL**, **Kích thước phôi**, **Chất liệu** theo PO. Dòng đã gửi in mà chưa giao có nền đỏ nhạt và nhãn cảnh báo. Chỉ bật **Xác nhận giao** sau khi tạo biểu thành công; nếu lỗi mẫu thì chưa ghi nhận lượt gửi in. “Đã gửi in” không bảo đảm máy in đã in ra giấy.

Khi giao phôi, Kho NVL mở **Xác nhận giao** và xác nhận trong popup. Tạm không nhập số thực giao; hệ thống lưu người giao, thời điểm và nhật ký, để số lượng chưa thu thập trống. Yêu cầu đã giao chuyển sang tab **Đã giao**, vẫn có thể in lại và không thể xóa lịch sản xuất đang liên kết.
