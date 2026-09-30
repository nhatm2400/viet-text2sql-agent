# Bổ sung CHECK constraints vào schema context — 30/09/2026

Đây là mốc trước khi thêm quy tắc khoảng ngày. Phép thử tiếp theo đạt 80% cho cả hai
phương án, với cùng CHECK constraints và output cap; xem [kết quả ngày](DATE_WINDOW_RESULTS.vi.md).

Đã chạy đủ 20 câu development cho baseline và agent với cùng giới hạn 4096 token.
**Baseline tăng từ 13/20 (65%) lên 14/20 (70%); LangGraph agent từ 13/20 (65%) lên
15/20 (75%) strict và relaxed execution accuracy.** Trong lượt mới, agent hơn baseline
1 câu, tương đương 5 điểm phần trăm; chưa chứng minh lợi thế ổn định qua nhiều lượt.

## Thay đổi thực hiện

`schema_tools.load_check_constraints()` đọc nguyên CHECK predicates từ AST của db/schema.sql,
bao gồm CHECK ở cột và ở bảng. Không tự viết danh sách enum trong prompt, không lấy giá trị
từ gold hoặc dữ liệu test. `schema_block()` và get_table_schema đưa constraints vào context.

Thêm 8 dòng CHECK trên 5 bảng: customers.segment/status, orders.status/channel,
payments.method/status, shipments.status, reviews.rating. Có cả giới hạn rating BETWEEN 1 AND 5.
Tùy chọn `--schema-context types-and-fks` giữ nguyên context trước thay đổi;
`with-checks` là mặc định mới. Exporter dùng `--axis schema-checks`, xác nhận context chỉ
thêm CHECK lines và toàn bộ model options giữ nguyên, gồm output cap 4096.

## Kết quả trước/sau

| Chỉ số | Baseline trước | Baseline +CHECK | Agent trước | Agent +CHECK |
|---|---:|---:|---:|---:|
| Strict EX | 13/20 (65%) | 14/20 (70%) | 13/20 (65%) | 15/20 (75%) |
| Relaxed EX | 13/20 (65%) | 14/20 (70%) | 13/20 (65%) | 15/20 (75%) |
| Câu có output cap hit | 3 | 2 | 2 | 2 |
| Câu không có SQL thực thi thành công | 3 | 2 | 2 | 2 |
| SQL thực thi được nhưng sai đáp án | 4 | 4 | 5 | 3 |
| p50 latency | 31,52 s | 31,34 s | 45,72 s | 40,15 s |
| p95 latency | 80,06 s | 78,36 s | 85,94 s | 96,44 s |
| Token trung bình/câu | 2.998,4 | 3.114,05 | 4.859,4 | 5.373,35 |

Token trung bình tăng khoảng 3,9% baseline và 10,6% agent. p95 agent tăng khoảng 12,2%.
Một câu agent mất 139,71 s nhưng vẫn sinh SQL đúng ngay lần execute đầu; p95 nearest-rank
trên 20 câu lấy quan sát thứ 19, nên p95 không bằng thời gian tối đa. Latency gồm gọi model
và tool, kể cả model call trả lời cuối. Điểm EX chỉ đánh giá kết quả SQL, không chấm câu diễn giải.

## Câu được sửa và câu giảm điểm

| ID | Baseline trước/sau | Agent trước/sau | Quan sát |
|---|---|---|---|
| cancelled_orders_north | Sai → đúng | Sai → đúng | Dùng đúng 'cancelled', không còn 'canceled' |
| cancelled_orders_central | Sai → đúng | Sai → đúng | Tương tự miền Bắc |
| revenue_q2_north | Sai → sai | Sai → đúng | Agent dùng < '2026-07-01'; baseline vẫn dùng <= '2026-06-30' |
| revenue_q2_central | Đúng → sai | Đúng → sai | Hai phương án dùng <= '2026-06-30', bỏ sót giao dịch có giờ ngày cuối quý |

Kết quả ròng: baseline thêm 2 đúng, mất 1; agent thêm 3 đúng, mất 1. Không bỏ câu giảm điểm
hoặc thay bằng kết quả cũ. Ba chiến lược context/budget đã đo có thể so sánh như các mốc dev:
2048 không CHECK = 60%/60%; 4096 không CHECK = 65%/65%; 4096 có CHECK = 70%/75%
(baseline/agent). Không cô lập tác dụng repair bằng chuỗi mốc này.

Lỗi còn lại ở agent:

- revenue_q2_central: mốc cuối ngày sai.
- units_2026_north: SUM quantity nhưng lọc status='cancelled' thay vì loại cancelled.
- units_2026_central: COUNT dòng và lọc sai cùng trạng thái.
- sold_categories_north/central: output cap 4096, chưa gọi execute_sql.

Không quan sát thấy self-correction qua lỗi SQL trong các ca được sửa: query đúng ở lần
execute đầu. Lợi ích quan sát được là từ cấu hình context mới, không phải bằng chứng repair uplift.

## Bằng chứng và kiểm thử

- Run trước: `eval/results/20260930-150626-760288-live-local-dev/`.
- Run sau: `eval/results/20260930-155530-314310-live-local-dev/`.
- [Chứng cứ từng cặp câu](evidence/schema-checks-4096-20260930.json): raw file hashes,
  model/data/source/context hashes, 8 CHECK lines thêm vào, SQL, latency, token, điểm và
  ID cải thiện/giảm điểm. Phản hồi model đầy đủ còn trong raw items.jsonl của mỗi run.
- Cùng snapshot `data/benchmark_v2_ready`, câu hỏi và gold không thay đổi; cùng model digest,
  Ollama version, temperature=0, seed=42, num_ctx=8192, think=true, cap=4096.
- Thứ tự phương án luân phiên theo câu, warm-up tách riêng, toàn bộ lỗi nằm trong mẫu số.
- **119 passed, 7 skipped** (chưa có PostgreSQL), 1 cảnh báo deprecation; lint/format đạt.
  Test mới kiểm tra CHECK ở cột/bảng, đúng spelling từ DDL, context cũ tái lập được, và
  từ chối so sánh nếu cùng lúc thay token hoặc thêm instructions ngoài CHECK.

Tái lập khi Ollama đang chạy:

```powershell
.venv/Scripts/python.exe -m eval.harness.live_local --split dev --num-predict 4096 --schema-context with-checks --date-windows unchanged
.venv/Scripts/python.exe -m eval.harness.compare_local --before eval/results/20260930-150626-760288-live-local-dev --after eval/results/20260930-155530-314310-live-local-dev --axis schema-checks --output docs/evidence/schema-checks-comparison-new.json
```

Nếu chạy model lại, thay --after bằng run mới. Không chọn lượt cao nhất nếu lặp nhiều lần.

## Giới hạn và bước tiếp theo

Đây là một lượt trên 20 câu từ 10 family × 2 miền, synthetic, AI-authored/AI-reviewed.
Context được phát triển trên dev đã xem kết quả; không gọi là held-out, human-reviewed hay
đánh giá PostgreSQL. Model có thể biến thiên dù seed cố định; chưa có độ tin cậy thống kê,
đo VI–EN, RAG, UI đầy đủ hoặc production. Execution accuracy có thể tình cờ khớp trên snapshot.
30 câu test chưa được chạy model.

Giữ CHECK constraints trong context vì schema có nguồn rõ và đã cải thiện mốc dev này.
Ưu tiên phép thử tiếp theo là quy tắc timestamp [start,end) với cùng context/budget.
Riêng câu quantity có cụm “loại đơn cancelled”: cần kiểm tra lại độ rõ của tiếng Việt trước
khi sửa prompt; không mặc định mọi sai khác đều là lỗi model. Nếu sửa câu hỏi để rõ hơn,
phải version benchmark và phân biệt với kết quả trên bộ câu hỏi hiện tại.

## Bullet CV hiện tại

Các bullet dưới đây mô tả riêng mốc CHECK. Bullet cho mốc mới nằm trong
[báo cáo khoảng ngày](DATE_WINDOW_RESULTS.vi.md).

```latex
\resumeItemPlain{Evaluated a local Qwen3-4B LangGraph agent on 20 Vietnamese development questions over a 12-table synthetic SQLite database, achieving 75\% strict execution accuracy versus a 70\% single-pass baseline with schema CHECK constraints in context.}
```

Hoặc nhấn mạnh cải thiện context:

```latex
\resumeItemPlain{Added schema-derived CHECK constraints to model context, raising agent strict execution accuracy from 65\% to 75\% on a 20-question synthetic development evaluation at a fixed 4,096-token output budget.}
```

Nêu được 75% với phạm vi trên, không đổi nhãn nguồn dữ liệu/review thành human.
