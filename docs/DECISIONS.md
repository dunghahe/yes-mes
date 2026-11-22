# Quyết định

## 2026-11-23 · Rà soát trước chuyển máy chủ

- Theo yêu cầu người dùng, rà soát giao diện, lỗi nghiệp vụ, phân quyền và bản đóng gói trước khi thay dịch vụ chính. Image kiểm tra được build riêng; không tự chuyển bản chạy chính khi các mục nghiệm thu còn mở.
- Giữ quy trình QC lô và hàng sửa đã chốt; không tự gán lô cho lịch sử cũ và không bổ sung QC Bavia/nhập kho đang hoãn.
- Chi tiết kiểm tra, lỗi đã sửa và giới hạn: `docs/PRE_RELEASE_REVIEW_20261123.md`. Hướng dẫn production riêng: `docs/deploy-linux.md`.

## 2026-11-22 · Giao phôi và hai chế độ xem lịch

- **Giao phôi:** Tạm thời không thu thập số lượng thực giao. Kho xác nhận qua popup; lưu thời điểm, tài khoản và audit. Số lượng để NULL, không dùng số kế hoạch thay cho số thực giao; số liệu cũ được giữ.
- **Điều kiện giao:** Chỉ cho xác nhận giao sau khi đã tạo thành công biểu sản xuất/Bavia để gửi in. Lỗi tạo biểu không ghi nhận lượt gửi in. Vẫn cho in lại sau khi giao. Hàng đã gửi in nhưng chưa giao có nền đỏ nhạt và nhãn cảnh báo.
- **Thông tin hàng chờ:** Thay cột số phôi và cặp/người làm bằng mã NVL, kích thước phôi và chất liệu lấy từ PO.
- **Bavia-only:** Vẫn yêu cầu đã xác nhận giao. Khi có phiếu giao chưa thu thập số lượng, tạm không áp giới hạn tổng Bavia dựa trên số phôi; không xem NULL là 0. Nếu toàn bộ phiếu có số lượng thực giao thì vẫn áp giới hạn dựa trên các số đã biết.
- **Lịch sản xuất:** Giữ hai chế độ **Tháng** và **Danh sách**, Tháng là mặc định theo lựa chọn người dùng. Danh sách hiển thị theo tuần, chọn riêng ngày, lọc kíp và tìm theo PO/mã/tên hàng. Nhấn đúp dòng để mở popup sửa; tạo mới lấy sẵn ngày/kíp đang chọn. Mọi thao tác lưu quay lại đúng chế độ và bộ lọc.

## 2026-11-22 · Mã lỗi và lịch tháng

- **Mã lỗi:** Bỏ Nhóm lỗi khỏi form tạo/sửa, danh sách và mẫu nhập Excel. Chỉ khai báo mã, tên và công đoạn phát hiện. Dữ liệu nhóm cũ trong database được giữ để bảo toàn lịch sử; không yêu cầu hoặc hiển thị khi thao tác mới.
- **Lịch nhiều hàng mỗi ngày:** Lịch tháng hiển thị tối đa 3 dòng trong mỗi ô ngày, dùng chiều cao cố định và nút **+N lịch** mở toàn bộ danh sách trong popup. Popup giữ bộ lọc PO/kíp hiện tại; người có quyền sửa chọn PO để mở form sửa. Không gộp hoặc thay đổi các dòng lịch đang có.

## 2026-11-22 · Danh sách yêu cầu và hàng đợi Kho NVL

- Danh sách **Yêu cầu xuất phôi** hiển thị số lượng PO cần hoàn thành; PO BAVIA_ONLY không hiển thị dòng “Không cần máy” trong cột người làm.
- Hàng đợi Kho NVL có bộ lọc **Chờ giao/Đã giao**. Tab Đã giao chỉ xem lại, không hiện thao tác xác nhận giao.
- Trên màn nhập Bavia, các trường thông tin đầu phiếu được căn đều trên một hàng khi đủ chiều rộng và tự co cột ở màn nhỏ.

## 2026-11-21 · Tra cứu và nhập QC/Sản lượng

- **Bố cục nhập liệu:** QC theo lô và Sản lượng dùng chung cách bố trí hai vùng: bên trái tìm/chọn lô hoặc yêu cầu; bên phải nhập hoặc xem dữ liệu của mục đang chọn. QC hỗ trợ tìm theo PO và mở trực tiếp bằng mã lô; Sản lượng lọc theo ngày/kíp/PO và mở trực tiếp bằng mã yêu cầu.
- **Trạng thái danh sách:** QC hiển thị Chưa QC/Đã QC theo việc đã có kết quả QC lưu; sản lượng hiển thị Chưa nhập/Đã nhập theo báo cáo đã lưu. Trạng thái in không quyết định trạng thái QC.
- **Tổng QC:** Người dùng nhập OK và tổng NG ở phần kết quả. Các dòng chi tiết NG tiếp tục ghi dạng lỗi, máy, hủy/sửa và số lượng; tổng chi tiết phải bằng tổng NG, còn OK + tổng NG phải bằng số lượng lô. Hệ thống tự tổng hợp phần NG hủy/sửa từ các dòng chi tiết.
- **PO BAVIA_ONLY và yêu cầu xuất phôi:** Vẫn tạo yêu cầu xuất phôi theo ngày/kíp và cấp mã yêu cầu như các PO khác. Không yêu cầu chọn cặp máy hoặc người làm máy. Mã yêu cầu được dùng để tìm/mở báo cáo Bavia.
- **Form sản lượng theo loại PO:** PO FULL có form Sản xuất và Bavia, chuyển giữa hai form bằng nút/tab trong cùng mục Sản lượng. PO SX_ONLY chỉ hiện Sản xuất; PO BAVIA_ONLY chỉ hiện Bavia. Bavia được nhập theo PO, ngày, kíp, người làm và số lượng, không phân bổ theo máy.
- **Số lượng đầu vào BAVIA_ONLY:** Chỉ nhập sản lượng Bavia sau khi Kho NVL xác nhận giao yêu cầu. Tổng sản lượng Bavia không vượt tổng phôi thực tế Kho NVL đã giao cho PO.

## 2026-11-19

- **Tách nhịp nhập sản lượng và QC:** Sản lượng tiếp tục ghi nhận theo ngày/kíp; QC chuyển sang theo dõi theo lô trên màn hình riêng. Một lô có thể gom sản phẩm liên tục từ nhiều ngày/kíp; QC được tổng hợp theo PO/lô, không gắn riêng vào một cặp máy hay kíp sản xuất.
- **Chia lô theo PO:** Khi tạo PO, người dùng nhập số lượng chuẩn mỗi lô. Phần mềm dựa vào số lượng đặt của PO để chia và tạo danh sách lô, tự cấp mã cho từng lô. Lô không gắn với máy; máy chỉ ghi ở từng dòng chi tiết NG.
- **In phiếu QC theo lô:** Kho được in trước một tập biểu cho các lô đã tạo từ PO, không cần chờ lô đủ sản lượng. Mỗi biểu có mã/QR duy nhất của một lô; QC dùng biểu theo thứ tự và nhập kết quả sau đó vào đúng mã lô.
- **Nội dung biểu theo lô:** In nguyên một trang theo ảnh người dùng gửi, kể cả phần gia công, QC và kho thành phẩm. Chưa có PDF gốc; dựng biểu bằng HTML/CSS. Phần mềm lưu chi tiết từng dạng NG, số lượng và máy; không bắt buộc ghi toàn bộ chi tiết lên giấy.
- **Giữ nguyên màn sản lượng:** Tiếp tục nhập sản lượng theo máy, ngày/kíp như hiện tại; không thêm thao tác quét lô vào màn này.
- **Quét lô ở màn QC:** Màn QC riêng cho phép quét mã lô và ghi kết quả kiểm cho toàn lô. Thời điểm QC lưu theo lúc hoàn tất kiểm.
- **Phạm vi chất lượng:** Kết quả OK/NG được tổng hợp theo PO/lô; không phân bổ chất lượng của lô về từng máy/kíp sản xuất.
- **Hiệu suất và OEE:** Hiệu suất/sản lượng và thời gian máy tiếp tục xem theo máy/kíp. OEE đầy đủ dùng chất lượng tổng hợp theo PO, không hiển thị OEE chất lượng riêng cho từng máy/kíp.
- **Lô cuối dư:** Nếu số lượng PO không chia hết cho cỡ lô, tạo lô cuối nhỏ hơn bằng số lượng còn lại (ví dụ 950 sản phẩm, cỡ lô 200: bốn lô 200 và một lô 150).
- **Thời điểm QC:** Ngày/kíp trên lượt QC là thời điểm hoàn tất kiểm thực tế, tách biệt với ngày/kíp sản xuất của hàng trong lô.
- **Lưu kết quả QC:** Ở phiên bản hiện tại, mỗi lượt QC ghi kết quả cho toàn bộ số lượng của lô; tổng OK + NG hủy + NG sửa phải khớp số lượng lô. Chưa chia một lô thành nhiều lượt QC từng phần; có thể mở rộng ở giai đoạn sau.
- **Chi tiết NG:** QC vẫn phân biệt NG hủy và NG sửa. Khi có NG, cho khai báo theo từng dạng lỗi, số lượng và máy gây lỗi.
- **Hàng sửa trong lô:** Hàng sửa quay lại giữ mã lô gốc. Mỗi lần mang đi sửa có mã phiếu riêng; QC lại ghi thành lượt riêng gắn với phiếu sửa và lô gốc. Hàng sửa không làm tăng sản lượng sản xuất.
- **Bavia:** Tạm dừng phần nhập liệu Bavia trong phạm vi phiên bản hiện tại; xem xét lại ở giai đoạn sau.

## 2026-11-16

- **Màn hình lịch sản xuất:** Chỉ dùng một trang lịch cho các vai trò có quyền xem. Nút **Tạo lịch** chỉ hiện khi tài khoản có quyền tạo; tạo mở popup, sửa bằng cách nhấn đúp vào thẻ lịch để tránh nút sửa dày đặc trên lịch kín. Đường dẫn cũ `/schedules/manage` chuyển về trang lịch chung.
- **Tạo yêu cầu từ lịch:** Trang lịch chỉ để xem và quản lý kế hoạch; không hiện lối tắt tạo yêu cầu phôi trên từng lịch. Tạo yêu cầu phôi thực hiện trong phân hệ riêng theo quyền vai trò.
- **Lịch thuộc ngày đã qua:** Cho phép tạo hoặc sửa lịch ngày quá khứ; hiển thị cảnh báo để người dùng rà soát, không chặn lưu.

## 2026-11-14

- **Nguồn công đoạn:** Chỉ khai báo công đoạn trên PO. Mã hàng chỉ lưu mã, tên và cycle time; xóa công đoạn mặc định khỏi form, Excel và database mã hàng. Công đoạn của PO hiện có được giữ nguyên.
- **Tên phân hệ kho:** Tên hiển thị và vai trò là “Kho NVL”; quyền vào hàng chờ, in biểu và xác nhận giao vẫn dựa trên quyền `blank_requests.deliver`.
- **Tạo PO và mã hàng:** Mở biểu mẫu tạo ngay trong popup trên trang danh sách. Nếu dữ liệu sai hoặc thiếu, giữ nguyên các giá trị đã nhập và hiện lỗi tại trường cần sửa.
- **Nhập PO và mã hàng từ Excel:** Có file mẫu, kiểm tra và xem trước trước khi nhập; nếu có bất kỳ lỗi nào thì chặn toàn bộ file, không nhập một phần. PO trong file tham chiếu mã hàng đang hoạt động. Xác nhận nhập phải chạy trong một transaction và ghi audit như tạo từng bản ghi.
- **Nhập Excel danh mục:** Admin nhập máy, cặp máy, nhân viên, mã lỗi, lý do dừng và ca/kíp bằng file mẫu có bước kiểm tra; lỗi ở bất kỳ dòng nào chặn toàn bộ file. Cặp máy chỉ nhận mã máy đã khai báo.
- **Lịch sản xuất:** Quyết định ban đầu tách trang xem và trang tạo; đã được thay bằng quyết định một trang chung ở mục 2026-11-16.

## 2026-11-13

- **Theo dõi lượt sửa:** Mỗi lần mang hàng đi sửa được cấp mã phiếu riêng, duy nhất, ngắn (ví dụ `SR-123`) và tự sinh để dễ ghi trên giấy. Khi hàng về, nhập mã phiếu và số lượng; mỗi lượt QC lại liên kết đúng một phiếu, không vượt số còn chờ của phiếu đó. Bảng tổng vẫn cộng theo PO/công đoạn. NG sửa đã lưu ở phần QC theo cặp được đưa vào hàng chờ sửa ngay cả khi 4 bước QC chưa hoàn tất; điều này không làm QC/OK thành phẩm được tính hoàn tất sớm.
- **Nhập kho thành phẩm:** Tạm bỏ khỏi phạm vi hiện tại; chưa có màn hình/API nhập kho. Chỉ xem xét tích hợp lại ở giai đoạn sau.
- **Thời gian chạy máy:** Không cho nhập phút chạy trong ca. Phút khả dụng lấy từ thời lượng ca/kíp trừ giờ nghỉ theo cấu hình; thời gian chạy tính bằng phút khả dụng trừ các phút dừng đã ghi. Ghi nhận đổi máy giữa ca được hoãn để cải thiện sau.
- **Cờ biểu có ghi dừng:** Đây là xác nhận biểu giấy có ghi/kiểm tra mục thời gian dừng (kể cả ghi 0), không phải xác nhận máy đã dừng. Nếu bỏ trống mục dừng trên giấy thì không tích; ứng dụng dùng 0 phút và đánh dấu kíp chưa ghi dừng để theo dõi độ đầy đủ dữ liệu OEE.
- **Máy và ca/kíp trên báo cáo:** Mỗi báo cáo nhập một ca/kíp. Không thêm ca/kíp, cặp máy hoặc đổi máy tại màn hình báo cáo; dùng máy/cặp Kỹ thuật đã khai báo trên yêu cầu phôi. Quyết định này thay cho các lựa chọn ngày 2026-11-12 và đầu ngày 2026-11-13 về thêm ca/kíp hoặc đổi máy.
- **Sửa báo cáo sản lượng:** Sau khi lưu, người có quyền sửa được mở lại và chỉnh báo cáo trong giai đoạn hiện tại. Mỗi lần sửa phải tăng phiên bản và ghi nhật ký trước/sau; vẫn chỉ có một nút lưu, không có trạng thái nháp riêng. Rà soát lại giới hạn sửa khi phần QC có dữ liệu phụ thuộc.
- **Mở báo cáo để sửa:** Không có nút “Sửa” riêng trong danh sách. Khi tìm kiếm mã yêu cầu phôi đã có báo cáo, tự mở toàn bộ dữ liệu báo cáo trong form để người có quyền sửa cập nhật trực tiếp.
- **Nhiều phiếu cùng PO/ngày/ca:** Màn hình báo cáo gom các yêu cầu phôi cùng PO, ngày sản xuất và ca/kíp vào một lượt xem/nhập; dữ liệu vẫn liên kết và lưu riêng theo từng yêu cầu, tổ và cặp máy.
- **Nhập QC sản xuất:** Trên trang báo cáo có phần QC lưu độc lập. Theo luồng 1:1, số đưa vào QC tự lấy từ sản lượng báo cáo; không yêu cầu nhập lại. Mục QC theo cặp chỉ nhập NG hủy và NG sửa; OK tự tính. Mục 4 bước ghi NG hủy, NG sửa và người QC theo từng bước. Tổng theo 4 bước phải khớp riêng với tổng theo cặp. QC Bavia được làm sau khi có báo cáo sản lượng Bavia.
- **Lưu từng phần QC:** Chỉ có một nút lưu. Mục QC theo cặp cần đủ dữ liệu cho tất cả cặp máy; trong mục 4 bước, từng dòng đủ NG hủy, NG sửa và người QC được lưu độc lập, các dòng trống được bỏ qua. Không bắt buộc hoàn tất cả bốn dòng trong cùng lần lưu. QC chỉ được tính vào OK thành phẩm và OEE khi đủ bốn bước và tổng NG hủy/NG sửa khớp; phần còn thiếu hoặc chưa khớp giữ trạng thái chưa hoàn tất.
- **Bavia, sửa và nhập kho:** Ghi sản lượng Bavia theo PO, ngày, kíp và người làm; FULL không được vượt OK QC sản xuất, BAVIA_ONLY không bị giới hạn này. QC Bavia lấy sản lượng làm số vào QC, chỉ ghi NG hủy/NG sửa. Bảng hàng chờ tổng hợp theo PO/công đoạn; từng lượt QC lại gắn với đúng mã phiếu sửa và không vượt số còn chờ trên phiếu. Nhập kho thành phẩm không vượt số đã đạt QC cuối cùng chưa nhập.
- **Vòng đời PO:** PO tự chuyển trạng thái theo dữ liệu gốc; ngưỡng tự đóng mặc định 100% số đặt và cấu hình bằng `po_auto_close_pct`. PO tự đóng sẽ mở lại nếu số thành phẩm đủ điều kiện giảm dưới ngưỡng; PO đóng tay không tự mở lại. Không giảm thành phẩm đủ điều kiện thấp hơn số đã nhập kho.

## 2026-11-14

- **Màu nhận diện giao diện:** Dùng xanh navy `#20499B` và xanh cyan `#2CA9E1` lấy từ logo Yamaguchi Vietnam; navy làm màu chính, cyan làm màu nhấn. Nền trắng, giao diện sáng cố định.
- **Người mang/nhận sửa:** Có thể chọn bất kỳ nhân viên đang hoạt động (công nhân, kỹ thuật, QC hoặc loại khác); hỗ trợ tìm theo mã hoặc tên. Không giới hạn theo loại nhân viên “Sửa chữa”.
- **Gợi ý nhân viên:** Mọi ô chọn nhân viên trong nhập báo cáo, phân công cặp máy, mang đi sửa và QC lại đều hỗ trợ tìm theo mã/tên và hiển thị danh sách gợi ý để chọn.

## 2026-11-12

- **Cột Máy của Bavia:** Chỉ ghi tay trên biểu in; không thêm dữ liệu Bavia theo máy vào phần mềm.
- **Nhóm máy:** Bỏ nhóm máy khỏi màn hình quản lý và luồng tạo/sửa yêu cầu phôi; chọn cặp máy trực tiếp. Giữ dữ liệu nhóm và liên kết cũ trong database để bảo toàn lịch sử.
- **Mẫu biểu in:** Admin được tải mẫu Excel `.xlsx` lên; ứng dụng lưu phiên bản, điền các key đã hỗ trợ, chuyển sheet tương ứng thành PDF và mở inline trên trình duyệt để người dùng bấm In. Không chạy macro/công thức trong mẫu.
- **Tên trên biểu xuất phôi:** “Người giao” là tài khoản Kho đang in biểu (sau khi giao, lấy người đã xác nhận giao); “Người nhận” là người đã tạo yêu cầu xuất phôi.
- **Mã QR trên biểu:** Phóng lớn mã QR, căn giữa trong vùng ô QR; chuyển nhãn/mã yêu cầu xuống dưới QR để không bị che.
- **Phân công người làm:** Khi tạo yêu cầu phôi, mỗi cặp máy gắn với đúng một người làm; lưu người làm trên chính dòng cặp và điền đúng người vào dòng tương ứng trên biểu.
- **Số lượng phôi yêu cầu:** Người yêu cầu không nhập số lượng. Kho tự cân đối và ghi số thực giao khi xác nhận giao; số lượng thành phẩm tiếp tục được nhập riêng trong báo cáo sản xuất. Dữ liệu cũ có số lượng yêu cầu được giữ để bảo toàn lịch sử.
- **Yêu cầu cũ chưa phân công theo cặp:** Chỉ tự khôi phục người làm khi yêu cầu cũ có đúng một cặp và một người. Trường hợp nhiều cặp không có dữ liệu ghép chính xác thì không tự suy đoán; Admin cần gán lại nếu muốn biểu in có người làm theo từng cặp.
- **Theo dõi hàng mang đi sửa:** Giai đoạn hiện tại ghi nhận từng lượt mang hàng đi sửa với PO, công đoạn, ngày, người nhận/đem sửa và số lượng; chưa phân rã số lượng theo loại lỗi.
- **Theo dõi vào QC lại:** Mỗi lượt QC lại phải liên kết với lượt mang đi sửa cụ thể và đúng công đoạn; cho phép theo dõi số đã vào QC lại so với số đã mang đi sửa, kể cả khi QC lại một phần. Báo cáo tổng vẫn cộng theo PO và công đoạn. Phân bổ số lượng theo từng loại lỗi để làm ở giai đoạn sau.
- **Màn hình nhập sản lượng và QC:** Dùng chung một trang theo bố cục biểu giấy; không yêu cầu lưu nháp hay chờ hoàn tất toàn bộ QC. Chỉ có một nút lưu QC để ghi phần cặp máy đủ dữ liệu và các dòng bước QC đã hoàn tất.
- **Nhập sản lượng cuối ca:** Ghi một tổng sản lượng cho mỗi cặp máy trong từng ca/kíp, không chia theo lô hoặc nhiều dòng sản lượng. Ngày sản xuất là ngày của ca; tổng ngày là tổng các ca. Giờ đầu/cuối lấy từ danh mục ca/kíp và không nhập trên form.
- **Đổi máy trong ca (đã hoãn ngày 2026-11-13):** Phương án trước là ghi riêng cặp máy cũ/mới; hiện chưa triển khai.

## 2026-11-11

- **Biểu QC:** Bỏ trường “Người QC” theo từng cặp máy ở mục QC gia công; giữ “Người QC” trong các phần kiểm tra phía dưới. Căn ba cột Sản lượng, NG hủy, NG sửa có độ rộng bằng nhau.
- **Biểu sản lượng Bavia:** Thêm cột “Máy” để người ghi tự điền trên biểu giấy.

## 2026-11-05

- **Biểu in:** Chưa chốt khổ giấy, hướng in và số cặp tối đa. Người dùng sẽ gửi biểu mẫu giấy khi bắt đầu giai đoạn làm biểu in. Tạm giữ A4 dọc theo thiết kế.
- **Khu sản xuất:** Khu là khu sản xuất và được gắn với từng máy; khu không phải nhóm máy.
- **Quyền bổ sung:** Quyền tạo, sửa hoặc xóa được cấp thêm phải đi kèm quyền xem.
- **QC Bavia:** Số lượng đưa vào QC không được lớn hơn sản lượng đã ghi nhận.
- **Xóa dữ liệu:** Chỉ cho xóa khi chưa có dữ liệu phụ thuộc nào ảnh hưởng đến hệ thống. Nếu đã có dữ liệu phụ thuộc thì chặn xóa và giữ lại bản ghi.
- **Nhập báo cáo:** Không có nút “Lưu nháp”. Người nhập gửi báo cáo bằng một thao tác xác nhận; chỉ báo cáo xác nhận thành công mới được tính vào tổng quan PO và OEE.
- **TOTP:** Bắt buộc với tài khoản Admin.
- **Môi trường:** Production chạy trên Linux; môi trường phát triển dùng Windows, có thể qua WSL2.
- **Truy cập từ xa:** Dùng Cloudflare Tunnel với Access; ứng dụng tự xác minh chữ ký, issuer, audience và thời hạn của Access JWT.
- **Phiên đăng nhập:** Tự hết hạn sau 60 phút không có thao tác; thao tác hợp lệ sẽ làm mới thời gian chờ.
- **Giới hạn đăng nhập theo IP:** 100 lần đăng nhập sai trong 10 phút cho mỗi IP; đồng thời mỗi tài khoản khóa 10 phút sau 5 lần sai.
- **Admin đầu tiên:** Tạo bằng lệnh CLI tương tác chạy trực tiếp trên máy chủ, chỉ khi chưa từng có tài khoản Admin; không tạo tài khoản Admin qua đăng ký web.
- **Mật khẩu ban đầu/đặt lại:** Hệ thống sinh mật khẩu ngẫu nhiên và chỉ hiển thị một lần cho Admin chuyển tới người dùng qua kênh riêng; tài khoản phải đổi ở lần đăng nhập tiếp theo.
- **Admin cuối cùng:** Luôn giữ ít nhất một Admin đang hoạt động; chặn khóa hoặc hạ vai trò Admin đang hoạt động cuối cùng.
- **Xóa lịch sản xuất:** Được xóa mềm dòng lịch nếu yêu cầu phôi chưa được xác nhận giao. Yêu cầu phôi chưa giao vẫn giữ liên kết tới lịch đã xóa mềm. Nếu đã xác nhận giao thì chặn xóa lịch.

# Quyết định bổ sung · 2026-11-12
- In biểu ngay trên trang hàng đợi hiện tại, không mở tab mới. Lần in đầu của một yêu cầu phôi in gộp biểu Sản lượng và QC; các lần sau cho phép in riêng từng biểu.

## 2026-11-19 · QC theo lô

- **Luồng sản lượng và QC:** Sản lượng tiếp tục nhập theo ngày, ca/kíp và cặp máy như hiện tại. QC là màn riêng; QC quét/nhập mã lô do hệ thống cấp, nhập kết quả cho toàn bộ số lượng lô và lưu riêng với báo cáo sản lượng.
- **Phân loại NG:** Khi lô có NG, nhập từng dạng lỗi, số lượng, máy gây lỗi và kết quả NG hủy/NG sửa. Tổng dòng chi tiết phải khớp từng tổng NG tương ứng của lô. Không gán toàn bộ lô cho một máy; máy chỉ gắn vào dòng lỗi khi QC ghi nhận.
- **In biểu QC:** Kho NVL có thể chọn/in một dải nhiều phiếu trước khi QC nhập liệu; không cần có kết quả QC mới được in. Mỗi lô in một trang biểu dựng bằng HTML/CSS theo ảnh giấy người dùng gửi, có QR/mã lô. Không cần PDF gốc; nút In mở hộp thoại in của trình duyệt ngay tại trang hiện tại.
- **Theo dõi sửa:** Mỗi lượt mang đi sửa thuộc một lô và có mã phiếu ngắn riêng. Khi hàng về, QC nhập mã phiếu, số vào QC lại và kết quả; dữ liệu QC lại tiếp tục gắn với lô ban đầu. Hàng sửa không cộng vào sản lượng sản xuất.
- **OEE sau khi QC theo lô:** A và P tiếp tục tính theo từng cặp máy/kíp. Do QC lô không xác định máy/kíp cho toàn bộ số OK, Q và OEE chỉ tính ở nhóm PO, dùng tỷ lệ OK lần đầu trên số đã vào QC; không phân bổ kết quả lô cho máy hoặc kíp.
- **Bavia:** Nhập liệu QC Bavia chưa nằm trong lát hiện tại.
- **Xem trước số lô trên PO:** Khi nhập số lượng đặt và số lượng mỗi lô, form PO hiển thị ngay số lô dự kiến và lượng dư ở lô cuối. Đây chỉ là xem trước; quy tắc tạo lô vẫn lấy từ dịch vụ lưu PO.
- **In biểu tại Kho NVL:** Chọn/in biểu QC theo lô mở trong popup ngay trên hàng đợi kho, không dùng vùng xổ dài trên trang.
- **Mẫu QC theo lô:** Biểu QC theo lô là một sheet Excel trong cùng mẫu quản lý với biểu sản lượng; in một trang A4 cho từng lô. Hệ thống điền thông tin PO/lô và QR, các phần ghi tay giữ trống.
- **Tổng hợp tại danh sách PO:** Hiển thị riêng sản lượng gia công, sản lượng Bavia, OK QC lần đầu và NG QC lần đầu (NG hủy + NG sửa); không cộng SX và Bavia vào một con số để tránh đếm trùng. PO chỉ Bavia hiển thị dấu gạch cho QC sản xuất vì phân hệ QC Bavia chưa nằm trong phiên bản hiện tại.
- **Thông báo Kho NVL:** Bỏ âm thanh báo phiếu mới; hàng đợi vẫn tự làm mới và đánh dấu phiếu vừa xuất hiện trên màn hình.
- **Cột Bavia trong danh sách PO:** Chỉ hiện cột này khi trang đang xem có PO thuộc công đoạn Bavia; các PO không có Bavia trong cùng bảng hiển thị dấu gạch.

## 2026-11-19 · Cập nhật mẫu in QC theo lô

- **Sheet mẫu:** Bỏ sheet QC cũ; mẫu Excel chỉ cần sheet Sản lượng và QC theo lô. QC theo lô vẫn được in riêng theo dải lô tại Kho NVL.
- **Mục II. Gia công:** Bố cục theo biểu giấy: Công đoạn OP1+OP2; ký hiệu máy; thời gian bắt đầu/kết thúc; số lượng OK/NG; người làm và kỹ thuật xác nhận.
- **Mục V:** Bỏ lý lịch sửa đổi tài liệu khỏi biểu QC theo lô.
- Các quyết định trước đây về lần in đầu gộp hai biểu và dùng sheet QC riêng đã được thay thế bởi quy trình QC theo lô.

## 2026-11-21 · Bố cục Phần I trên biểu in

- Trên cả biểu Sản lượng và QC theo lô, nhãn và giá trị ở Phần I nằm trên cùng một dòng; nội dung dài tự co vừa ô để tránh xuống dòng.
- Phần I của QC theo lô dùng cùng nhịp chiều cao dòng với biểu Sản lượng; giữ nguyên các trường riêng của lô và vùng QR.

## 2026-11-21 · Giao diện nhập sản lượng

- Giao diện toàn ứng dụng ưu tiên sử dụng trên PC; màn tạo yêu cầu xuất phôi cần dùng thuận tiện trên điện thoại.
- Màn nhập sản lượng bỏ tiêu đề Ca/kíp lặp; phân nhóm cặp máy bằng nền xanh nhạt. Chỉ dùng màu vàng nhạt khi biểu có ghi nhận dừng máy; màu sắc dùng để phân biệt nội dung và trạng thái, không trang trí dày đặc.

## 2026-11-23 · Đăng nhập MES qua hostname công khai

- Người dùng vào hostname MES công khai qua Cloudflare Tunnel và đăng nhập trực tiếp bằng tài khoản MES; không yêu cầu xác thực Cloudflare Access trước đó. `CLOUDFLARE_ACCESS_REQUIRED=false`.
- Giữ xác thực nội bộ MES, giới hạn đăng nhập sai và TOTP bắt buộc cho Admin. Đây là lựa chọn giảm một lớp chặn ngoài; trang đăng nhập MES có thể được mọi người trên Internet truy cập.

