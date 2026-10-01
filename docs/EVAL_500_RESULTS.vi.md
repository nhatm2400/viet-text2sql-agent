# Kết quả eval 500 câu để ghi CV — 02/10/2026

Đã chạy và dừng ở **đúng 500 câu**, worker đã thoát. Đã replay prediction/gold trên
database có hash cố định, kiểm tra scoring, token usage, summary và source snapshots.
[Báo cáo tổng hợp](evidence/vitext2sql-prefix-500-20261002.json) không chứa câu hỏi, SQL
hoặc raw responses của dataset bên ngoài.

| Chỉ số | Kết quả |
|---|---:|
| Câu hỏi đã đánh giá | **500** |
| Database đã phủ | **15 / 42** trong package hợp lệ |
| Cặp database–SQL AST khác nhau, gồm literal | 332 |
| Strict execution accuracy của repo | **61,0% — 305/500** |
| Relaxed execution accuracy của repo | **72,6% — 363/500** |
| Strict trên gold không rỗng | 60,45% — 298/493 |
| Gold trả rỗng | 7 |
| Câu chạm output cap ít nhất một model call | 40 |
| Câu không có SQL thực thi thành công | 36 |
| Latency p50 / p95 | 58,43 / 108,78 giây |
| Tokens trung bình mỗi câu, gồm các model calls | 4.531,09 |

Strict là chỉ số chính; relaxed chấp nhận một số khác biệt về projection và thứ tự cột.
40 câu chạm cap và 36 câu không thực thi thành công vẫn nằm trong mẫu số 500; hai nhóm
có thể chồng lấp, không cộng chúng như các loại lỗi độc lập.

## Phạm vi và lựa chọn cutoff

Đây là **500 câu hợp lệ đầu tiên theo thứ tự nguồn**, từ package adapted ViText2SQL
test-v2: câu hỏi tiếng Việt ghép với gold/database Spider gốc có schema tiếng Anh.
Người dùng chọn cutoff khoảng 500 sau khi quan sát tiến độ 490 câu để giới hạn thời gian.
Không chọn lại câu theo đúng/sai, không đổi prompt/model/scoring sau khi xem điểm để lấy
lượt trả lời tốt hơn. Các phiên resume giữ cả câu sai đã ghi. Helper phiên cuối chỉ đặt
tín hiệu pause sau prediction thứ 500, trước khi nhận câu mới; code eval đóng băng giữ nguyên.

Qwen3 4B Q4_K_M local qua Ollama 0.34.4; temperature=0, seed=42, think=true, context=8192,
output cap=4096 mỗi call. LangGraph tối đa hai lần thử SQL, ba vòng tool; các calls trả lời
cuối được tính vào latency/tokens. Read-only SQLite, không inject LIMIT. Scorer là
strict/relaxed execution agreement của repo, không phải evaluator leaderboard chính thức.

500 câu là quy mô hợp lý để mô tả một đánh giá sơ bộ cho prototype trên CV, có số đo
và bằng chứng tái lập. Phạm vi mới phủ 15/42 database và có cấu trúc SQL lặp lại, nên
không dùng tỷ lệ này như ước lượng đại diện cho toàn bộ test. Chưa có independent human
sample audit cho bản thích nghi. Không ghi 1.000/1.618 câu đã đánh giá hoặc official EX.

## Câu CV có thể dùng

> Benchmarked a local Qwen3 4B LangGraph Text-to-SQL agent on a 500-question adapted ViText2SQL subset across 15 SQLite databases, achieving 61.0% strict execution accuracy.

```latex
\resumeItemPlain{Benchmarked a local Qwen3 4B LangGraph Text-to-SQL agent on a 500-question adapted ViText2SQL subset across 15 SQLite databases, achieving 61.0\% strict execution accuracy.}
```

Ghi rõ subset trong CV và liên kết repo/report để người đọc kiểm tra cách chọn 500 câu
và định nghĩa metric. Có thể giữ riêng bullet về agent nghiệp vụ 12 bảng PostgreSQL;
61,0% ở trên được đo trên SQLite của benchmark ngoài.

## Tái kiểm chứng

```powershell
.venv/Scripts/python.exe -m eval.harness.report_vitext2sql --run eval/results/20261001-030508-057723-vitext2sql-test --prefix-size 500 --output eval/results/verify-prefix-500-new.json
```

Lệnh không gọi model, chỉ replay SQL và xuất aggregate. Report giữ hashes config,
items, progress, manifest, questions, exclusions và code snapshots. Raw evidence nằm
trong thư mục Git ignore; nguồn ngoài tải bằng downloader đã pin version/hash.

Checkpoint full run vẫn là **500/1.618**, còn **1.118 câu**; không tạo `summary.json`
giả cho full run. Report prefix ghi rõ subset complete và full run incomplete.
Không tự tiếp tục phần còn lại. Kiểm chứng tại thời điểm chốt eval: **162 passed,
7 skipped** PostgreSQL; lint/format đạt. Đây là snapshot trước khi dựng PostgreSQL thật.

Ngày 02/10 đã thêm provider cho app và dựng demo PostgreSQL riêng; xem
[demo và kiểm chứng mới](LOCAL_POSTGRES_DEMO.vi.md). Source app hiện tại khác snapshots
của run 500, nên không resume run cũ bằng checkout mới hoặc sửa hashes. Báo cáo trên
vẫn giữ nguyên 305/500 và 363/500; demo mới không làm thay đổi metric benchmark.
