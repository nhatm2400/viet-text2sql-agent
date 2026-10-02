# Hướng dẫn review đủ 50 câu

Mục tiêu: xác nhận câu hỏi rõ nghĩa và SQL đáp án mẫu (gold SQL) tính đúng điều được hỏi.
Bạn đang kiểm tra đề và đáp án của bài thi, chưa chấm bài model. Chạy được SQL, số liệu trông
hợp lý, hoặc AI nói đúng đều chưa đủ để duyệt. Không cần kiểm tra thủ công mọi dòng database.

## 1. Mở công cụ

Mở http://127.0.0.1:8502 trong trình duyệt. Nếu không vào được, mở PowerShell tại repo và chạy:

```powershell
.venv/Scripts/python.exe -m streamlit run ui/database_review.py --server.address 127.0.0.1 --server.port 8502 --server.headless true --browser.gatherUsageStats false
```

Giữ terminal chạy khi dùng trang. Database là `data/benchmark_v2_ready/snapshot.sqlite`.
Trang chỉ đọc, không gọi model và không lưu quyết định review. Tab đáp án có cả dev và test;
chạy gold test để kiểm tra nhãn không phải chạy model trên test.

## 2. Làm quen dữ liệu

Trong tab **1. Xem bảng**, chọn từng bảng. Phần cấu trúc có tên cột và khóa liên kết.
100 dòng đầu chỉ là mẫu xem, không phải toàn bộ dữ liệu.

| Bảng | Một dòng thường đại diện cho |
|---|---|
| regions | Một miền |
| customers | Một khách hàng |
| addresses | Một địa chỉ của khách; một khách có thể có nhiều địa chỉ |
| suppliers | Một nhà cung cấp |
| categories | Một nhóm hàng, có thể có nhóm cha |
| products | Một sản phẩm |
| inventory | Tồn kho của một sản phẩm tại một kho |
| orders | Một đơn hàng |
| order_items | Một dòng sản phẩm trong đơn, có quantity riêng |
| payments | Một bản ghi thanh toán với trạng thái và thời điểm riêng |
| shipments | Một bản ghi giao hàng |
| reviews | Một đánh giá của khách về sản phẩm |

Đọc câu hỏi để quyết định cần đếm loại dòng nào. Không mặc định một dòng order_items là một
sản phẩm đã bán: quantity có thể lớn hơn 1. Miền của khách, địa chỉ và nhà cung cấp có thể khác nhau.

## 3. Quy trình lặp cho từng câu

1. Tab **2. Xem đáp án mẫu** → chọn dev hoặc test → chọn ID câu.
2. Trước khi đọc SQL, viết lại yêu cầu bằng lời: đếm/tính gì, lọc gì, thời gian theo cột nào,
   chia nhóm nào, trả những cột nào, sắp thứ tự thế nào. Nếu có hai cách hiểu hợp lý, ghi “cần làm rõ”.
3. Đọc SQL theo thứ tự: FROM/JOIN → WHERE → GROUP BY/HAVING → SELECT → ORDER BY/LIMIT.
4. Bấm **Chạy SQL đáp án mẫu**. Ghi kết quả hoặc số dòng. SQL chạy được là bước kiểm tra kỹ thuật.
5. Sang tab **3. Tự chạy SELECT**, chạy phép đối chiếu phù hợp: phân nhóm nhỏ hơn, liệt kê ID,
   kiểm tra số dòng bị nhân khi JOIN, hoặc kiểm tra ngày biên. Không chỉ chạy lại cùng SQL.
6. Ghi quyết định và lý do. Nếu chưa giải thích được SQL làm gì, để “chưa rõ”, không duyệt.

| SQL | Hiểu đơn giản |
|---|---|
| COUNT(*) | Đếm dòng sau JOIN và lọc |
| COUNT(DISTINCT x) | Đếm các giá trị x khác nhau |
| SUM(x) / AVG(x) | Tổng / trung bình của x |
| WHERE | Lọc dòng trước khi chia nhóm |
| GROUP BY | Chia dữ liệu thành các nhóm |
| HAVING | Lọc nhóm sau khi tổng hợp |
| EXISTS / NOT EXISTS | Có / không có bản ghi liên quan thỏa điều kiện |
| LEFT JOIN | Giữ cả dòng bên trái không có bản ghi tương ứng bên phải |
| ORDER BY / LIMIT | Xếp thứ tự / giới hạn số dòng |

## 4. Ba ví dụ thực hành

### A. active_customers_north

Câu hỏi đếm khách active miền Bắc. Gold phải lọc miền qua customers.region_id và status active.
Đối chiếu bằng bảng đầy đủ theo miền và trạng thái:

```sql
SELECT r.region_code, c.status, COUNT(*) AS customer_count
FROM customers c JOIN regions r ON r.region_id = c.region_id
GROUP BY r.region_code, c.status
ORDER BY r.region_code, c.status;
```

So ô NORTH/active với gold. Preview được chuẩn bị trước ghi 1354; đây là số cần đối chiếu,
không phải chỉ dẫn phải chấp nhận đáp án. Muốn kiểm tra từng khách, chạy:

```sql
SELECT c.customer_id, c.status, r.region_code
FROM customers c JOIN regions r ON r.region_id = c.region_id
WHERE r.region_code = 'NORTH' AND c.status = 'active'
ORDER BY c.customer_id;
```

Trang chỉ hiện tối đa 500 dòng, vì vậy không dùng số dòng hiển thị của danh sách này thay COUNT.

### B. cancelled_orders_north

Đếm đơn cancelled, miền theo khách của đơn, thời gian theo orders.created_at.
Từ 01/01 đến trước 01/07/2026 phải là `>= '2026-01-01' AND < '2026-07-01'`.
Không thay bằng completed_at hoặc lọc thời điểm hủy vì câu hỏi nói ngày đặt.

```sql
SELECT substr(o.created_at, 1, 7) AS month, COUNT(*) AS n
FROM orders o
JOIN customers c ON c.customer_id = o.customer_id
JOIN regions r ON r.region_id = c.region_id
WHERE r.region_code = 'NORTH' AND o.status = 'cancelled'
  AND o.created_at >= '2026-01-01' AND o.created_at < '2026-07-01'
GROUP BY substr(o.created_at, 1, 7)
ORDER BY month;
```

Cộng số đơn của các tháng và so với gold (preview cũ: 359). Phép đối chiếu tháng hỗ trợ
kiểm tra khoảng thời gian, nhưng vẫn cần đọc đúng WHERE; hai SQL cùng sai vẫn có thể khớp.

### C. revenue_q2_north

Câu hỏi ghi rõ payments.amount, succeeded, paid_at quý 2. Không lấy orders.total_amount,
không lọc theo ngày đặt, không JOIN thêm order_items làm nhân tiền thanh toán.

```sql
SELECT substr(p.paid_at, 1, 7) AS month,
       COUNT(*) AS joined_rows,
       COUNT(DISTINCT p.payment_id) AS unique_payments,
       SUM(p.amount) AS amount_unrounded
FROM payments p
JOIN orders o ON o.order_id = p.order_id
JOIN customers c ON c.customer_id = o.customer_id
JOIN regions r ON r.region_id = c.region_id
WHERE r.region_code = 'NORTH' AND p.status = 'succeeded'
  AND p.paid_at >= '2026-04-01' AND p.paid_at < '2026-07-01'
GROUP BY substr(p.paid_at, 1, 7)
ORDER BY month;
```

Chỉ có tháng 04-06; joined_rows bằng unique_payments cho biết JOIN này không nhân payment.
Cộng tổng chưa làm tròn rồi làm tròn cuối cùng đến 2 số để đối chiếu gold. Cộng các tổng đã
làm tròn theo tháng có thể khác vài xu. Con số lớn trên dữ liệu synthetic không chứng minh
doanh thu thực hoặc tính đại diện của dữ liệu.

## 5. Checklist 20 câu dev

Mỗi dòng bên dưới có hai câu `_north` và `_central`. Kiểm tra cả hai, gồm mã miền và kết quả;
không duyệt câu thứ hai chỉ vì SQL giống câu thứ nhất.

| Tiền tố ID | Điểm cần xác nhận |
|---|---|
| active_customers | COUNT khách active; miền qua customers |
| cancelled_orders | COUNT đơn cancelled; created_at trong H1/2026; miền qua khách |
| revenue_q2 | SUM payments.amount succeeded; paid_at quý 2; round 2; không nhân payment |
| units_2026 | SUM order_items.quantity; created_at năm 2026; loại cancelled; không COUNT dòng |
| low_stock | COUNT dòng inventory với quantity <= reorder_level; miền nhà cung cấp |
| active_products | Sản phẩm active; miền nhà cung cấp; không tự lọc nhà cung cấp active |
| delivered_shipments | COUNT shipment delivered; miền qua khách của đơn |
| positive_reviews | COUNT review rating >= 4, kể cả 4 sao; miền của người review; toàn kỳ |
| default_addresses | COUNT địa chỉ mặc định; miền qua addresses.region_id, không qua khách |
| sold_categories | COUNT DISTINCT category_id; đơn không cancelled; toàn kỳ; miền khách |

## 6. Checklist 30 câu test

Đây là hướng dẫn hỗ trợ review, không phải kết luận rằng gold đã đúng. Không dùng gold test
để tạo few-shot, chỉnh prompt hoặc sửa agent theo từng câu. Nếu phải làm vậy, cần công bố
test bị dùng cho phát triển và chuẩn bị bộ test mới.

| ID | Điểm cần kiểm tra |
|---|---|
| test_01 | SUM succeeded amount quý 2 theo paid_at; nhóm method + segment; thứ tự 2 cột |
| test_02 | Đếm khách có >= 2 method khác nhau của payment succeeded; không đếm payment |
| test_03 | Tỷ lệ hủy = đơn cancelled / mọi đơn H1 theo kênh × 100; ngày đặt; round 2 |
| test_04 | AVG orders.total_amount quý 2 theo ngày đặt; có ít nhất 1 payment succeeded; mỗi đơn 1 lần |
| test_05 | Khách không có bất kỳ đơn nào; không chỉ không có đơn completed |
| test_06 | Đếm khách có >= 3 đơn completed H1 theo created_at |
| test_07 | Top 5 category theo SUM quantity; completed năm 2026; hòa chọn category_id tăng |
| test_08 | Sản phẩm không xuất hiện trong bất kỳ order_items nào, kể cả đơn cancelled |
| test_09 | Theo warehouse: SUM quantity và COUNT DISTINCT product_id; xếp warehouse |
| test_10 | Tổng quantity mọi kho bằng 0; cần làm rõ sản phẩm không có dòng inventory có tính không |
| test_11 | Supplier active; chỉ đếm product active; giữ supplier có 0 product; COUNT product ID |
| test_12 | >= 10 review; AVG rating làm tròn 2; xếp theo điểm đã làm tròn rồi product_id; top 5 |
| test_13 | Product active không có review; không tự lọc thời gian |
| test_14 | Theo method: đếm payment succeeded và SUM amount, round 2; toàn kỳ |
| test_15 | Đơn không cancelled và không tồn tại payment succeeded; payment failed vẫn có thể thuộc nhóm |
| test_16 | SUM amount của payment status refunded; không tự suy ra tiền hoàn từ nguồn khác |
| test_17 | Đếm shipment delivered theo carrier; n giảm dần, carrier tăng khi hòa |
| test_18 | delivered_at - shipped_at > 5 × 24 giờ; đúng 5 ngày không tính; không đếm ngày lịch |
| test_19 | Đếm khách có > 1 địa chỉ; không đếm tổng số địa chỉ |
| test_20 | Khách DISTINCT có ít nhất 1 địa chỉ city = TP.HCM; không đếm trùng |
| test_21 | COUNT khách theo segment; customers.created_at quý 1/2026 |
| test_22 | 100 × SUM(discount) / SUM(total_amount + discount), completed; không AVG tỷ lệ từng đơn |
| test_23 | Top 10 đơn completed theo total_amount giảm; hòa order_id tăng; đúng 2 cột |
| test_24 | unit_price > AVG giá tất cả sản phẩm; không tự chỉ dùng product active |
| test_25 | Self-JOIN categories: child.parent_category_id = parent.category_id; chỉ nhóm có cha |
| test_26 | DISTINCT khách có đơn completed theo kênh, H1 theo created_at |
| test_27 | Khách có completed ở cả web và app; không phải web hoặc app |
| test_28 | Product có >= 3 warehouse khác nhau; quantity = 0 vẫn tính |
| test_29 | COUNT đơn theo segment khách + status đơn; không COUNT khách; thứ tự 2 cột |
| test_30 | Đếm payment succeeded quý 2 theo paid_at nhưng orders.created_at trước quý 2 |

## 7. Các tình huống cần xử lý trước khi duyệt

- **Câu mơ hồ:** viết rõ định nghĩa, sửa câu hỏi/gold nếu cần. Ví dụ test_10 hiện chỉ xét sản phẩm
  có dòng inventory; chưa nên tự cho rằng sản phẩm không có dòng inventory là tồn kho 0.
- **Kết quả rỗng hoặc số 0:** phân biệt không có dòng với một dòng giá trị 0. Kiểm tra nhóm dữ liệu
  trước khi lọc để biết vì sao không có đáp án; SQL sai có thể tình cờ cũng trả rỗng.
- **SUM không có dòng:** thường ra NULL; nếu muốn 0 phải nói rõ và xử lý nhất quán.
- **JOIN:** kiểm tra số ID khác nhau và tổng số dòng. Có nhiều order_items cho một order là bình
  thường, nhưng SUM orders.total_amount sau JOIN đó có thể bị nhân.
- **Top-k:** cần quy tắc hòa rõ ràng, tránh thứ tự không ổn định làm chấm sai.
- **Sửa gold/câu hỏi:** ghi lại lý do. Preview trong REVIEW.md không tự cập nhật; phải chạy lại.
  Không sửa snapshot để ép đáp án đúng. Khi sửa định nghĩa/dataset, lưu thành phiên bản mới và
  ghi nhận khác với phiên bản đã dùng cho kết quả dev 60%; không sửa đè báo cáo lịch sử.

## 8. Ghi nhận review

Có thể giữ ghi chú riêng hoặc gửi vào chat, không cần tự sửa JSON. Mẫu cho mỗi câu:

```text
ID: active_customers_north
Người review: <tên/định danh thực>
Hiểu yêu cầu: đếm khách active thuộc miền Bắc
Đã kiểm tra: bảng/cột, bộ lọc, JOIN, kết quả đối chiếu
SQL đối chiếu: phân nhóm theo miền và trạng thái
Kết quả đối chiếu: <kết quả bạn thực sự chạy>
Quyết định: duyệt / cần sửa / chưa rõ
Lý do hoặc chỗ cần sửa: ...
```

Chỉ câu đã kiểm tra mới cập nhật trong questions.json:

```json
"human_review": "approved",
"reviewer": "<người thực sự review>"
```

Chưa rõ thì để pending. Không cần cố duyệt đủ trong một buổi. Chia 5 câu/buổi, làm dev trước,
rồi test theo ID. Nếu chưa tự tin đọc SQL, bạn duyệt phần ý nghĩa và nhờ người hiểu SQL kiểm tra
phần logic; ghi rõ ai làm phần nào. AI có thể giải thích/kiểm tra bổ sung nhưng không tự trở thành
người review. Tự review có thể gọi author-reviewed, không gọi independently reviewed.

## 9. Khóa benchmark và chạy test

Trước khi khóa: đủ 50 ID được kiểm tra; câu mơ hồ đã giải quyết; nguồn synthetic/AI-assisted
vẫn được ghi; đã kiểm tra overlap và mức đa dạng giữa dev/test. 20 dev chỉ là 10 family × 2 miền.
Test có các phép toán giống dev nên không tuyên bố tổng quát sang ý định hay schema chưa từng thấy.

Chốt model/prompt/ngân sách bằng dev trước khi chạy model trên test. Runner hiện yêu cầu duyệt
cả 20 dev và 30 test, giữ nguyên snapshot và đủ reviewer. Với package hiện tại:

```powershell
.venv/Scripts/python.exe -m eval.harness.prepare_v2 --package data/benchmark_v2_ready --freeze
.venv/Scripts/python.exe -m eval.harness.live_local --package data/benchmark_v2_ready --split test
```

Nếu tạo package phiên bản mới, thay đường dẫn của cả hai lệnh. Freeze ghi hash câu hỏi và kiểm
tra gold chạy được; nó không kiểm chứng ngữ nghĩa thay con người. Ollama cần đang chạy cho lệnh
eval. Giữ mọi lỗi trong mẫu số, công bố model/digest, dataset/split, strict/relaxed, latency và
ngân sách. Không chạy thử nhiều lần rồi chọn lượt cao nhất. Muốn tiếp tục tune theo lỗi test,
giữ kết quả mốc này và chuẩn bị test mới.

Kết quả có thể gọi là đánh giá nội bộ trên bộ câu hỏi synthetic đã được con người review.
Nó không tự trở thành benchmark công khai hay bằng chứng hệ thống sẵn sàng production.
