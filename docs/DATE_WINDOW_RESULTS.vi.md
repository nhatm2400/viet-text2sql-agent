# Quy tắc khoảng ngày trên timestamp — 01/10/2026

Đã chạy đủ 20 câu development × 2 phương án với output cap 4096 và CHECK constraints.
**Baseline tăng từ 14/20 (70%) lên 16/20 (80%); agent từ 15/20 (75%) lên 16/20 (80%)**
ở cả strict và relaxed execution accuracy. Không có câu giảm điểm trong lượt này.
Hai chiến lược hiện ngang điểm; chưa có bằng chứng agent vượt baseline ở cấu hình mới.

## Kết quả trước/sau

| Chỉ số | Baseline trước | Baseline +quy tắc ngày | Agent trước | Agent +quy tắc ngày |
|---|---:|---:|---:|---:|
| Strict EX | 14/20 (70%) | 16/20 (80%) | 15/20 (75%) | 16/20 (80%) |
| Relaxed EX | 14/20 (70%) | 16/20 (80%) | 15/20 (75%) | 16/20 (80%) |
| Câu có output cap hit | 2 | 2 | 2 | 2 |
| Câu không có SQL thực thi thành công | 2 | 2 | 2 | 2 |
| SQL thực thi được nhưng sai đáp án | 4 | 2 | 3 | 2 |
| p50 latency | 31,34 s | 29,85 s | 40,15 s | 32,89 s |
| p95 latency | 78,36 s | 79,61 s | 96,44 s | 92,97 s |
| Token trung bình/câu | 3.114,05 | 3.228,05 | 5.373,35 | 5.104,7 |

Baseline thêm 2 câu đúng (+10 điểm phần trăm), agent thêm 1 (+5 điểm phần trăm).
Token trung bình baseline tăng khoảng 3,7%; agent giảm khoảng 5,0%. p95 của baseline
tăng khoảng 1,6%; agent giảm khoảng 3,6%. Latency có thể thay đổi theo trạng thái runtime
và phần cứng; một lượt không chứng minh tối ưu tốc độ. p95 dùng nearest-rank trên 20 câu.
Agent dùng nhiều token và có p95 cao hơn baseline ở cùng mức EX trong lượt mới.

| ID | Baseline trước/sau | Agent trước/sau | SQL trong lượt mới |
|---|---|---|---|
| revenue_q2_north | Sai → đúng | Đúng → đúng | paid_at >= '2026-04-01' AND paid_at < '2026-07-01' |
| revenue_q2_central | Sai → đúng | Sai → đúng | Cùng khoảng ngày, đúng miền tương ứng |

Cả hai phương án trả lời đúng hai câu doanh thu quý 2. Các câu được sửa có SQL đúng
ngay lần execute đầu; không quan sát thấy repair qua một truy vấn lỗi trước đó. Vì vậy
không gọi phần tăng điểm này là self-correction uplift.

Bốn câu sai ở mỗi phương án:

- `units_2026_north/central`: baseline SUM quantity nhưng lọc status='cancelled';
  agent COUNT dòng order_items và cùng lọc nhầm cancelled. Gold yêu cầu SUM và loại cancelled.
- `sold_categories_north/central`: hết output cap 4096 trước khi xuất SQL/tool call;
  baseline bị policy chặn SQL rỗng, agent chưa thực thi SQL. Không phải truy vấn đúng bị chặn.

Các mốc dev đã đo (baseline/agent): 2048 không CHECK = 60%/60%; 4096 không CHECK =
65%/65%; 4096 có CHECK = 70%/75%; 4096 có CHECK và quy tắc ngày = 80%/80%.
Giữ nguyên kết quả của từng mốc; không ghép các dự đoán tốt nhất từ nhiều run.

## Thay đổi và phạm vi đo

Thêm một quy tắc dùng chung trong `src/t2sql/agent/prompts.py`: với khoảng ngày lịch
trên cột timestamp, dùng `>= start AND < exclusive_end`. Mốc cuối là đầu kỳ tiếp theo,
hoặc đầu ngày kế tiếp nếu người dùng yêu cầu tính cả ngày cuối. Quy tắc giữ nguyên điều
kiện giờ cụ thể và ngưỡng thời lượng khi câu hỏi yêu cầu. Không sửa SQL của model bằng
postprocessing, không thêm ngày hoặc đáp án của benchmark vào prompt.

Quy tắc được nối vào context của cả baseline và agent. System prompt của ứng dụng dùng
cùng constant; phép đo này vẫn chỉ đánh giá hai chiến lược trong `live_local`, không phải
toàn bộ UI, RAG hay clarification của ứng dụng.

Giữ nguyên Qwen3 4B, model digest, Ollama 0.34.4, CHECK constraints, temperature=0,
seed=42, num_ctx=8192, think=true, output cap=4096 mỗi model call, snapshot, 20 câu dev
và gold SQL. Mỗi cấu hình chạy một lượt đầy đủ, cả baseline và agent; không chọn kết quả
cao nhất qua nhiều lượt. Warm-up tách riêng, thứ tự phương án luân phiên theo câu, mọi
lỗi được giữ trong mẫu số. Thời gian và token bao gồm cả model call trả lời cuối của agent.

## Bằng chứng và kiểm thử

- Run trước: `eval/results/20260930-155530-314310-live-local-dev/`.
- Run sau: `eval/results/20260930-164502-433648-live-local-dev/`.
- [Chứng cứ so sánh](evidence/date-windows-4096-20260930.json): 40 cặp dự đoán trước/sau,
  raw hashes, context/source/data hashes, quy tắc thêm vào, SQL, token, latency và điểm.
  Exporter tính lại metrics từ raw items thay vì lấy số được gõ trong báo cáo.
- Snapshot: `data/benchmark_v2_ready`, SHA-256
  `bb4f8c9127389527e9905622979db6c35b6b6ace91ee40c5ef5b31ee74b89e70`.
- Questions SHA-256: `2695b833253463aa59faf5d33585b0dccd7dcfca4d9727c2b18b54b1fb8a8ecc`.
- Adapter, agent graph, scoring, schema tools và DDL có cùng source hashes trước/sau.
  Runner thêm tùy chọn và metadata; context mới chỉ nối thêm đúng constant quy tắc ngày.
- **122 passed, 7 skipped** vì chưa có PostgreSQL, 1 cảnh báo deprecation; lint đạt.
  Test khoảng ngày kiểm tra đầu kỳ, ngày cuối lúc 00:00 và 23:59:59, đầu kỳ tiếp theo:
  khoảng nửa mở trả SUM=7, điều kiện cũ `<= '2026-06-30'` trả SUM=1 trên TEXT timestamps
  của SQLite. Các dòng ngoài kỳ bị loại. Đây là kiểm chứng ngữ nghĩa ranh giới, không
  phải số đo độ đúng của model.
- Test exporter từ chối so sánh nếu thêm instruction khác hoặc đồng thời đổi token cap.

Tái lập khi Ollama đang chạy:

```powershell
# Context trước thay đổi
.venv/Scripts/python.exe -m eval.harness.live_local --split dev --num-predict 4096 --schema-context with-checks --date-windows unchanged
# Context thêm quy tắc ngày
.venv/Scripts/python.exe -m eval.harness.live_local --split dev --num-predict 4096 --schema-context with-checks --date-windows half-open
# Thay run paths bằng hai run vừa tạo; output phải là file mới
.venv/Scripts/python.exe -m eval.harness.compare_local --before eval/results/20260930-155530-314310-live-local-dev --after eval/results/20260930-164502-433648-live-local-dev --axis date-windows --output docs/evidence/date-windows-comparison-new.json
```

## Giới hạn

Đây là development trên 20 câu synthetic từ 10 family × 2 miền, AI-authored/AI-reviewed.
Không phải human-reviewed test accuracy, held-out family, phép đo PostgreSQL hoặc production.
Prompt được phát triển sau khi xem dev; 30 câu test chưa được chạy model. Một lượt với
seed cố định vẫn có thể biến thiên, chưa chứng minh cải thiện ổn định qua nhiều lượt.
Execution accuracy có thể khớp tình cờ trên một snapshot. Câu trả lời diễn giải không được chấm.

Cụm “loại đơn cancelled” trong hai câu quantity có thể gây nhầm giữa loại trừ và loại đơn;
nếu làm rõ tiếng Việt, cần tạo phiên bản benchmark mới và đo riêng. Không thay câu hỏi
giữa hai lượt rồi trình bày như cùng bộ dữ liệu.

## Bullet CV có thể dùng

```latex
\resumeItemPlain{Evaluated a local Qwen3-4B LangGraph Text-to-SQL agent on 20 Vietnamese development questions over a 12-table synthetic SQLite database, achieving 80\% strict execution accuracy at a 4,096-token output budget.}
```

Hoặc tập trung vào thay đổi vừa đo:

```latex
\resumeItemPlain{Added shared timestamp-window guidance, raising strict execution accuracy from 75\% to 80\% for a local LangGraph agent and from 70\% to 80\% for a single-pass baseline on a fixed 20-question synthetic development set.}
```

Nêu được 80% với phạm vi development trên SQLite; không diễn giải thành kết quả human-reviewed
hoặc PostgreSQL. Bước tiếp theo là làm rõ câu quantity trong một benchmark version riêng,
sau đó đo riêng khả năng sinh SQL của nhóm danh mục mà không gộp hai thay đổi.
