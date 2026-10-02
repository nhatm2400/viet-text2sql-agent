# So sánh 2.048 và 4.096 token - 30/09/2026

Đây là mốc trước khi thêm CHECK constraints vào context. Phép thử tiếp theo đạt 70% baseline
và 75% agent ở 4096 token; xem [kết quả context](SCHEMA_CHECK_RESULTS.vi.md).

Đã hoàn tất pilot 4 câu từng thất bại, sau đó chạy đủ 20 câu development cho cả baseline
và LangGraph agent. **Cả hai phương án tăng từ 12/20 (60%) lên 13/20 (65%) strict và
relaxed execution accuracy.** Chỉ một câu mới đúng ở mỗi phương án; agent vẫn ngang baseline.

## Kết quả toàn bộ 20 câu

| Chỉ số | Baseline 2048 | Baseline 4096 | Agent 2048 | Agent 4096 |
|---|---:|---:|---:|---:|
| Strict EX | 12/20 (60%) | 13/20 (65%) | 12/20 (60%) | 13/20 (65%) |
| Relaxed EX | 12/20 (60%) | 13/20 (65%) | 12/20 (60%) | 13/20 (65%) |
| Câu có model call hết output cap | 8 | 3 | 8 | 2 |
| Câu không có lần SQL thực thi thành công | 8 | 3 | 8 | 2 |
| SQL thực thi được nhưng đáp án sai | 0 | 4 | 0 | 5 |
| p50 latency | 29,29 s | 31,52 s | 38,79 s | 45,72 s |
| p95 latency | 39,17 s | 80,06 s | 40,22 s | 85,94 s |
| Token trung bình/câu | 2.396 | 2.998,4 | 3.536,7 | 4.859,4 |

Tăng **5 điểm phần trăm**, không phải 5 câu. Câu mới đúng: `revenue_q2_central` ở cả hai
phương án; không có câu vốn đúng ở run cũ bị sai trong run mới. 12 câu cũ vẫn đúng.
p95 tăng khoảng gấp đôi; token trung bình tăng khoảng 25% baseline và 37% agent.
Với 20 câu và một lượt mỗi cấu hình, chưa kết luận cải thiện có ý nghĩa thống kê hoặc
độ biến thiên latency. Đây là development tuning trên dataset synthetic AI-authored,
không phải test được con người review hay đo PostgreSQL.

## Pilot và giới hạn tái lập

Pilot chọn trước 4 câu `_north`: cancelled_orders, revenue_q2, units_2026, sold_categories.
Baseline đúng 1/4; agent 0/4. Không cộng 8 dự đoán pilot vào mẫu số 20 câu của bảng trên.

`revenue_q2_north` đúng ở baseline pilot nhưng sai ở baseline run đầy đủ. Model vẫn có thể
trả SQL khác nhau dù cùng temperature=0 và seed=42. Giữ cả hai kết quả, không chọn pilot
thay thế câu sai. Báo cáo sử dụng nguyên một run đầy đủ, và cần nhiều lượt nếu muốn đo độ ổn định.

## Những lỗi đã thấy ở 4.096 token

| Câu | Baseline | Agent | Bằng chứng |
|---|---|---|---|
| cancelled_orders_north/central | SQL chạy, sai | SQL chạy, sai | Dùng status='canceled' thay vì 'cancelled', trả 0 |
| revenue_q2_north | SQL chạy, sai | SQL chạy, sai | paid_at <= '2026-06-30' loại giao dịch có giờ ngày 30/6; gold dùng < '2026-07-01' |
| units_2026_north | SQL chạy, sai | SQL chạy, sai | COUNT dòng thay SUM quantity, và lấy cancelled thay vì loại cancelled |
| units_2026_central | Hết token, SQL rỗng | SQL chạy, sai | Agent có cả lỗi COUNT và đảo điều kiện trạng thái |
| sold_categories_north/central | Hết token, SQL rỗng | Hết token, chưa gọi tool | done_reason=length với output cap 4096 |

Tăng token giúp một số câu tạo SQL, nhưng SQL chạy thành công không đồng nghĩa đáp án đúng.
Trong các ca sai ngữ nghĩa trên, database không trả lỗi nên cơ chế repair theo lỗi thực thi
không được kích hoạt. Chưa có bằng chứng tăng accuracy nhờ self-correction.

## Cấu hình và bằng chứng

Cùng Qwen3 4B digest, runtime Ollama v0.34.4, schema/glossary/prompt, snapshot và câu hỏi.
Temperature=0, seed=42, num_ctx=8192, think=true. Chỉ đổi num_predict từ 2048 sang 4096;
giới hạn này áp dụng mỗi model call, bao gồm reasoning. Agent có nhiều model calls nên
tổng token/câu có thể cao hơn output cap. SQL budgets, scoring và quy tắc thứ tự giữ nguyên.
Warm-up không tính latency, thứ tự hai phương án luân phiên, toàn bộ lỗi nằm trong mẫu số.

- Run 2048: `eval/results/20260929-180317-358297-live-local-dev/`.
- Pilot 4096: `eval/results/20260930-145221-811436-live-local-dev/`.
- Run đầy đủ 4096: `eval/results/20260930-150626-760288-live-local-dev/`.
- [Bằng chứng trước/sau](evidence/token-budget-2048-vs-4096-20260930.json): từng cặp câu,
  trạng thái, SQL, điểm, token, latency, model/data/source hashes và hashes của raw files.
- [Bằng chứng pilot](evidence/token-budget-pilot-4096-20260930.json).
- Raw config và model responses còn trong các run git-ignored; exporter đọc kết quả thực,
  từ chối run thiếu câu hoặc khác model/prompt/data. Không dùng fixture thay model.
- Kiểm thử mã sau thay đổi: **116 passed, 7 skipped** (PostgreSQL chưa cấu hình),
  1 cảnh báo deprecation từ LangGraph; Ruff check/format đạt.

Tái lập khi Ollama đang chạy:

```powershell
.venv/Scripts/python.exe -m eval.harness.live_local --split dev --num-predict 4096 --schema-context types-and-fks --date-windows unchanged --ids cancelled_orders_north revenue_q2_north units_2026_north sold_categories_north
.venv/Scripts/python.exe -m eval.harness.live_local --split dev --num-predict 4096 --schema-context types-and-fks --date-windows unchanged
.venv/Scripts/python.exe -m eval.harness.compare_local --before eval/results/20260929-180317-358297-live-local-dev --after eval/results/20260930-150626-760288-live-local-dev --output docs/evidence/token-budget-comparison-new.json
```

Nếu chạy lại, dùng đường dẫn run mới cho --after. Exporter từ chối ghi đè file chứng cứ.

## Quyết định và bước tiếp theo

Giữ 4096 như mốc thí nghiệm đã đo để so sánh lần sửa tiếp theo. Chưa coi tăng token là
giải pháp chính: thêm một câu đúng đổi lấy p95 khoảng gấp đôi. Runner vẫn mặc định 2048;
muốn dùng cấu hình mới truyền --num-predict 4096.

Ưu tiên tiếp theo trên dev là cung cấp các giá trị enum hợp lệ từ CHECK constraints trong
schema context (schema_block ở mốc này chỉ liệt kê cột/type/FK), hướng dẫn khoảng thời gian
timestamp dạng [start,end), và kiểm tra SUM/DISTINCT/phủ định. Đây là đề xuất chưa được đo;
không sửa prompt theo từng gold test. 30 câu test vẫn chưa được chạy.

## Phạm vi các lượt chạy

80 dự đoán = 20 câu × 2 phương án × 2 cấu hình; không phải 80 câu độc lập. Pilot thêm
8 dự đoán nằm ngoài 80. Các câu/gold được AI hỗ trợ tạo và review; chưa có human review.
