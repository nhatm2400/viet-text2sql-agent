# Kết quả model local — 30/09/2026

Đây là mốc 2048 token được giữ nguyên. Phép thử tiếp theo ở 4096 token đạt 65% trên cùng
20 câu dev, kèm p95 khoảng gấp đôi; xem [bảng trước/sau](TOKEN_BUDGET_RESULTS.vi.md).

Đã chạy model thật, không replay fixture: Qwen3 4B qua Ollama v0.34.4 trên RTX 4050
Laptop 6 GB, cùng snapshot SQLite v2, cùng schema 12 bảng và glossary.
Đây là **preliminary development evaluation**, chưa có human review, chưa chạy test.

## Kết quả đầy đủ

| Phương án | Strict EX | Relaxed EX | p50 | p95 | Token trung bình/câu |
|---|---:|---:|---:|---:|---:|
| Sinh SQL một lượt | 12/20 (60%) | 12/20 (60%) | 29,29 s | 39,17 s | 2.396 |
| LangGraph + execute_sql | 12/20 (60%) | 12/20 (60%) | 38,79 s | 40,22 s | 3.536,7 |

Chênh lệch accuracy là **0 điểm phần trăm**. Không có bằng chứng agent cải thiện accuracy
trong phép đo này. Agent dùng thêm lượt model để trả lời sau tool; so sánh đo toàn bộ hai
chiến lược, không phải ablation riêng của repair. Token gồm prompt và output, kể cả reasoning;
không tương đương chi phí tiền. Không tốn phí API; điện và phần cứng chưa được định lượng.

20 câu là **10 query family × 2 miền**, AI-assisted, trên dữ liệu tổng hợp. Không phải
20 ý định độc lập, không đo dữ liệu doanh nghiệp thực, PostgreSQL, RAG, VI–EN, hoặc UI đầy đủ.
Chỉ chạy một lượt mỗi câu/phương án; chưa đo độ biến thiên qua nhiều lần chạy.

## Phân tích lỗi

Hai phương án đúng cùng 12 câu: active_customers, low_stock, active_products,
delivered_shipments, positive_reviews, default_addresses, mỗi family có 2 miền.

Mỗi phương án sai 8 câu thuộc cancelled_orders, revenue_q2, units_2026, sold_categories.
Tất cả 16 phản hồi thất bại có `done_reason=length`, chạm output cap 2.048 token và
không tạo SQL: baseline bị policy chặn SQL rỗng; agent kết thúc mà không gọi tool.
Đây là lỗi hoàn thành đầu ra trong ngân sách, chưa chứng minh model viết SQL sai ngữ nghĩa.
Trong lượt này không quan sát thấy repair thành công; không công bố self-correction uplift.

Lượt smoke trước đó (`20260929-175919-126877-live-local-dev`, 2 câu) dùng `think=false`
gặp reasoning lẫn vào content. Sau khi xác minh giao thức, đã đổi sang `think=true` cho
cả hai phương án để Ollama trả reasoning riêng. Giữ nguyên log smoke và không gộp vào bảng trên.
Trong lượt đầy đủ không đổi prompt, gold, model hay ngân sách theo câu.

## Bằng chứng và tái lập

- Run đầy đủ: `eval/results/20260929-180317-358297-live-local-dev/`.
- [Bản chứng cứ gọn](evidence/qwen3-4b-dev-20260930.json): từng câu, SQL/lần thử,
  kết quả, latency, token, hashes của raw files, source, model, snapshot và câu hỏi.
  Raw response đầy đủ còn trong `items.jsonl` của run; thư mục raw đang git-ignored.
- Snapshot: `data/benchmark_v2_ready`, candidate-3; SHA-256
  `bb4f8c9127389527e9905622979db6c35b6b6ace91ee40c5ef5b31ee74b89e70`.
- Model digest: `359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7`.
- temperature=0, seed=42, num_ctx=8192, num_predict=2048, think=true;
  baseline tối đa 1 SQL attempt, agent tối đa 2; SQL deadline 5 s.
- Warm-up loại khỏi latency; thứ tự phương án luân phiên theo câu. Latency gồm model và
  thực thi SQL, không gồm chạy gold. Các ca lỗi vẫn nằm trong mẫu số và percentile.
- Kiểm thử mã: **109 passed, 7 skipped** (cần PostgreSQL), 1 cảnh báo deprecation;
  Ruff check và format đều đạt.

```powershell
.venv/Scripts/python.exe -m eval.harness.live_local --split dev --schema-context types-and-fks --date-windows unchanged
```

Cần khởi động runtime đã cài trước, xem [hướng dẫn](LIVE_LOCAL_EVAL.vi.md).
Giữ đúng model digest và snapshot; không mặc định tag model hoặc seed đảm bảo kết quả
bit-for-bit trên mọi runtime/phần cứng. Không cần tải lại model hay dùng API key.

## Nội dung CV

Nếu muốn nêu kết quả model, dùng câu có đủ phạm vi:

```latex
\resumeItemPlain{Evaluated a local Qwen3-4B LangGraph agent on 20 AI-authored Vietnamese development questions over a 12-table synthetic SQLite database, achieving 60\% strict execution accuracy; benchmarked against a single-pass baseline with the same 60\% result.}
```

Đây là kết quả thật nhưng còn thấp và bộ dev nhỏ. Với CV ngắn, có thể ưu tiên năng lực
xây dựng phép đo thay vì dùng accuracy làm điểm nhấn:

```latex
\resumeItemPlain{Built and ran a reproducible local Text-to-SQL evaluation with 40 baseline/agent predictions, strict/relaxed execution scoring, latency and token tracking, and per-query failure traces.}
```

Giữ bullet mô tả agent trong [bản CV trước](LOCAL_EVAL_AND_CV.vi.md), chọn một trong hai
bullet trên. Không ghi 100% từ kiểm chứng gold thành accuracy của model.

## Để có mốc đánh giá được con người kiểm tra

Không có nhãn “official” tự động khi runner chạy xong. Bước còn thiếu là người hiểu SQL
kiểm tra định nghĩa câu hỏi và gold, sửa những chỗ chưa đúng, rồi khóa phiên bản benchmark.
`data/benchmark_v2_ready/REVIEW.md` đã chứa câu hỏi, SQL và preview để làm việc đó.
Hướng dẫn [review/freeze](LIVE_LOCAL_EVAL.vi.md#review-nghĩa-là-gì) giải thích từng bước.
Chưa đánh dấu approved thay người dùng; 30 câu test chưa được chạy.

Mốc tiếp theo nên xử lý giới hạn reasoning/output trên dev rồi chốt cấu hình trước khi chạy
test đã review. Một kết quả test tự xây vẫn cần công bố nguồn synthetic và mức đa dạng;
không tự trở thành benchmark công khai hoặc kết quả tổng quát.
