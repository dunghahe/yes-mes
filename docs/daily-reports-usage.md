# Nhập báo cáo sản lượng

Mở **Sản lượng**. Bên trái, lọc yêu cầu theo ngày/kíp/PO hoặc quét, nhập mã yêu cầu để mở trực tiếp. Danh sách cho biết yêu cầu **Chưa nhập** hay **Đã nhập**. Chọn một yêu cầu để nhập hoặc xem báo cáo ở bên phải. Màn hình lấy PO, mã hàng, ngày lịch, ca/kíp, cặp máy và người làm từ yêu cầu. Người nhập báo cáo vào cuối ca, ghi một tổng sản lượng cho mỗi cặp máy; không tách theo lô. Mỗi báo cáo chỉ có một ca/kíp và dùng cặp máy đã khai báo trên yêu cầu phôi. Ghi nhận đổi máy giữa ca được hoãn để cải thiện sau.

Ở ô **PO**, gõ một phần mã để xem gợi ý. Chọn PO trong danh sách để lọc yêu cầu; vẫn có thể nhập mã rồi bấm **Tìm danh sách**.

Giờ bắt đầu và kết thúc lấy từ danh mục ca/kíp, không nhập trên form. Phút khả dụng tính tự động từ thời lượng ca trừ giờ nghỉ; thời gian chạy là phút khả dụng trừ thời gian dừng đã nhập. Checkbox xác nhận biểu giấy có ghi hoặc kiểm tra mục dừng (kể cả ghi 0); nếu mục này để trống trên giấy thì không tích, ứng dụng dùng 0 phút và đánh dấu dữ liệu dừng chưa được ghi. Hiệu suất trên 100% chỉ hiện cảnh báo.

Chọn **Lưu báo cáo sản lượng** để ghi nhận chính thức. Báo cáo đã lưu được tính vào tổng quan và OEE; người có quyền sửa có thể mở lại để chỉnh. Mỗi lần sửa được lưu nhật ký trước/sau.

QC được nhập riêng tại **QC theo lô**. Sản lượng vẫn lưu theo ngày/kíp và cặp máy; không nhập lô trong màn này. Báo cáo sản lượng đã xác nhận mới được tính vào sản lượng và OEE. QC kiểm tra mã lô riêng và không được xác nhận số QC vượt tổng sản lượng đã xác nhận của PO.

Với PO **FULL**, dùng nút **Sản xuất/Bavia** để chuyển hai form trên cùng trang. PO **SX_ONLY** chỉ có form Sản xuất; PO **BAVIA_ONLY** chỉ có form Bavia. Có thể mở form Bavia từ mã yêu cầu phôi; BAVIA_ONLY phải được Kho NVL xác nhận giao trước khi nhập sản lượng. Bavia ghi theo PO, ngày, kíp và người làm, không chia theo máy.
