# Review bằng AI - 30/09/2026

Đã đọc yêu cầu và gold SQL của đủ **50 câu** (20 dev, 30 test), kiểm tra join, bộ lọc,
định nghĩa tiền/thời gian, DISTINCT, thứ tự và trường hợp không có dữ liệu. Đã chạy
đối chiếu trên snapshot, thêm Python references cho 30 test và 12 tình huống biên.
Đây là **AI-reviewed**, không phải human-reviewed hoặc independent review.

## Kết quả thực thi

| Phép kiểm tra | Kết quả |
|---|---:|
| Gold SQL khớp phép tính Python theo hàng/cột/thứ tự | 50/50 |
| SQL sau policy rewrite giữ nguyên đáp án | 50/50 |
| Ca biên với kết quả mong đợi viết riêng | 12/12 |
| Biến thể SQL cố ý sai bị phát hiện trên ca biên | 12/12 |

Python references đọc bảng thô, dùng dictionary, set, Counter và Decimal; không đọc/phân
tích gold SQL để tạo đáp án. Dev tái dùng reference cũ, test có implementation Python mới.
Cả SQL và Python vẫn do AI hỗ trợ viết, có thể cùng hiểu sai một định nghĩa. Kết quả này
không chứng minh đúng trên mọi dữ liệu và **không phải accuracy mới của model**.

## Phát hiện và xử lý

1. **test_10 chưa rõ về sản phẩm không có inventory.** Gold hiện chỉ xét sản phẩm có
   bản ghi inventory. Đã làm rõ câu hỏi trong gói mới: chỉ xét sản phẩm có ít nhất một
   bản ghi; tổng quantity mọi kho bằng 0; không tính sản phẩm chưa có bản ghi inventory.
   Không đổi gold SQL hay snapshot. Đây là quy ước benchmark, không phải xác nhận nghiệp vụ thực.
2. **Ba ca có bằng chứng snapshot yếu:** test_08 và test_13 trả một dòng giá trị 0;
   test_10 trả không có dòng. SQL sai có thể tình cờ trùng những kết quả này. Đã thêm ca biên
   có đáp án khác 0/rỗng và SQL mutation để kiểm tra logic. Các ca biên chưa được đưa vào
   mẫu số eval model; không khẳng định đã loại bỏ mọi false positive của execution accuracy.
3. **Tập câu hỏi có overlap:** 20 dev là 10 family × 2 miền; test có cùng phép toán và bảng
   với dev, như payment totals, review, shipment. Có thể dùng như mốc nội bộ trên schema cố định,
   không gọi là đánh giá tổng quát sang query family hoặc database chưa thấy.
4. **Câu hỏi đã chỉ rõ nhiều tên cột và quy tắc.** Điều này giúp gold ít mơ hồ nhưng dễ hơn
   hội thoại nghiệp vụ tự nhiên. Chưa kiểm chứng clarification, ý định mơ hồ hoặc ngôn ngữ VI-EN.
5. Không thấy sai khác kết quả gold/Python trên snapshot này. Không đổi điểm model 60% đã đo,
   không chạy model trên test, không tự gắn reviewer là người dùng.

## 12 tình huống được kiểm chứng

| Câu | Tình huống |
|---|---|
| test_04 | Một đơn có hai payment succeeded vẫn chỉ đóng góp một lần vào AVG |
| test_08 | Có cả sản phẩm chưa bán và sản phẩm có nhiều order_items |
| test_10 | Hai kho tổng 0, một kho 0 nhưng kho khác dương, sản phẩm không có inventory |
| test_11 | Supplier active có 0 product active vẫn xuất hiện với số đếm 0 |
| test_13 | Phân biệt product active chưa review, inactive chưa review, product đã review |
| test_18 | Đúng 5 ngày bị loại; vượt mốc 1 giây được tính; kém mốc 1 giây và NULL bị loại |
| test_20 | Một khách có hai địa chỉ TP.HCM chỉ tính một khách |
| test_22 | Tỷ lệ trên tổng giá trị, tránh nhầm mẫu số sau giảm giá |
| test_23 | Đơn bằng tiền xếp ID tăng; đơn cancelled nhiều tiền bị loại |
| test_27 | Phải có cả web lẫn app completed; hai đơn web chưa đủ |
| test_28 | quantity 0 vẫn tính kho; hai bản ghi cùng kho không thành hai kho |
| test_30 | Biên đầu/cuối quý theo paid_at và điều kiện created_at trước quý |

Mỗi ca có một mutant vẫn thực thi được nhưng cho kết quả khác. Đây là 12 ví dụ phát hiện
lỗi ngữ nghĩa, không phải 12 lớp lỗi đã được kiểm tra đầy đủ mọi biến thể.

## Gói dữ liệu và bằng chứng

- Gói cũ giữ nguyên: `data/benchmark_v2_ready/`.
- Gói mới: `data/benchmark_v2_ai_reviewed/`, version `benchmark-v2-ai-reviewed-1`.
  Có REVIEW.md mới, câu test_10 rõ hơn, từng item có metadata ai_review.
  Trạng thái human_review vẫn pending; không có frozen.json.
- [Bằng chứng từng câu và ca biên](evidence/ai-review-original-20260930.json).
- [Bằng chứng kiểm tra lại gói đã sửa](evidence/ai-review-revised-20260930.json).
- Trình xem dữ liệu hiện vẫn mặc định mở gói cũ. Snapshot và gold giống nhau nên kết quả
  chạy không đổi; muốn đọc câu test_10 đã làm rõ, xem REVIEW.md của gói mới.

Tái lập từ repo, không cần Ollama hoặc API:

```powershell
.venv/Scripts/python.exe -m eval.harness.ai_review
.venv/Scripts/python.exe -m eval.harness.ai_review --package data/benchmark_v2_ai_reviewed
.venv/Scripts/python.exe -m pytest tests/test_ai_review.py -q
```

Muốn tạo lại bản chỉnh câu hỏi ở đường dẫn khác chưa tồn tại:

```powershell
.venv/Scripts/python.exe -m eval.harness.ai_review --revision data/benchmark_v2_ai_reviewed_new
```

Không cần người dùng review lại chỉ để nhận kết quả kiểm chứng AI này. Nếu công bố số liệu,
ghi đúng nguồn **AI-authored, AI-reviewed synthetic benchmark**; cơ chế freeze/test hiện tại
vẫn yêu cầu human review và chưa bị bỏ qua. Review bằng AI không tự làm kết quả trở thành
“official” hoặc “human-verified”.
