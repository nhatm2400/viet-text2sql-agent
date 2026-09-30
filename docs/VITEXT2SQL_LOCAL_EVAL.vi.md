# ViText2SQL với Qwen3 4B local — 01/10/2026

Đã tích hợp tải nguồn cố định, chuẩn bị database/gold và runner nhiều schema có checkpoint.
Kết quả benchmark bên ngoài được giữ riêng với mốc 80% trên 20 câu nghiệp vụ synthetic.
Không lấy 80% đó làm tỷ lệ dự kiến trên tập lớn.

## Nguồn và cách thích nghi

[ViText2SQL của VinAI](https://github.com/VinAIResearch/ViText2SQL) cung cấp câu hỏi, tên
bảng/cột và SQL tiếng Việt. [Paper](https://aclanthology.org/2020.findings-emnlp.364/)
mô tả quá trình dịch bởi người và split theo database. Repo không cung cấp file SQLite.
[Spider chính thức](https://yale-lily.github.io/spider) cung cấp database và SQL gốc tiếng Anh.

Để đo đúng thiết lập của dự án — câu hỏi tiếng Việt, schema tiếng Anh — pipeline ghép
annotation ViText2SQL với Spider bằng cùng db_id và **AST SQL khớp hoàn toàn, gồm literal**.
Đồng thời kiểm tra layout chỉ số bảng/cột, types, PK và FK của hai schema. Không bỏ qua
giá trị khi ghép, không chèn giá trị gold vào SQL do model sinh, không đưa gold vào prompt.
Mọi bản SQL gốc khớp AST phải cho cùng kết quả trên database gốc trước khi chấp nhận câu.

Nhãn kết quả là **adapted ViText2SQL questions over original Spider English schemas**.
Đây không phải full ViText2SQL nguyên bản, điểm leaderboard Spider hay metric chính thức.
ViText2SQL được tác giả dịch/kiểm tra bởi người; bản thích nghi này mới được kiểm chứng
bằng chương trình, chưa có independent human sample audit. Không đổi nhãn đó thành human-reviewed.

Nguồn cố định:

- VinAI commit: `e759141d891feb794bb9a9fb912d544b25583b3c`.
- Spider archive từ liên kết trên trang tác giả, SHA-256:
  `00636695dabed6b5f4b8328a16b13e069a2f16591d5efcce57660669c85b121b`.
- Sử dụng cả train_spider, train_others và dev trong cùng archive để đối chiếu, vì ViText2SQL
  chia lại database của corpus Spider. Không dùng split Spider làm split ViText2SQL.
- Metadata GitHub Spider tham khảo cũng có commit/hashes; package dùng annotations và
  database trong cùng archive. Hashes từng file có trong `data/external/vitext2sql/sources.json`.

## Preflight toàn bộ nguồn

| Chỉ số | Dev | Test |
|---|---:|---:|
| Số câu ở commit hiện tại | 954 | 1.908 |
| Khớp AST và literal | 902 | 1.619 |
| Gold chạy được và các variants đồng ý | **898** | **1.618** |
| Database trong package | 25 | 42 |
| Gold trả 0 dòng | 15 | 174 |
| Không khớp AST/literal | 52 | 289 |
| Gold lỗi SQLite hoặc mã hóa | 4 | 1 |

Test ở commit hiện tại có 1.908 câu; paper năm 2020 ghi 1.906. Báo cáo số thực đọc từ
nguồn đã pin. **898/1.618 là số câu hợp lệ đã chuẩn bị, chưa phải số câu model đã chạy.**
Danh sách loại trừ được tạo trước inference, không dựa vào câu model trả lời sai.
Không diễn giải EX trên subset hợp lệ thành EX trên toàn bộ 954/1.908 câu nguồn.

Dev loại thêm 2 gold có ORDER BY đặt trước INTERSECT không hợp lệ trong SQLite và 2 gold
gặp TEXT chứa byte không giải mã được UTF-8. Test loại thêm 1 gold trỏ đến bảng không có
trong database tải về. Không sửa gold hoặc thay database để làm các câu này đạt điểm.

Packages dùng hiện tại:

- `data/external/vitext2sql/packages/dev-v3/`.
- `data/external/vitext2sql/packages/test-v2/`.

Các bản preflight trước được giữ để truy nguyên; không gộp với package mới. ViText2SQL
cấm tái phân phối dữ liệu gốc hoặc dữ liệu đã sửa. Raw sources, packages và model outputs
chỉ nằm trong `data/` và `eval/results/`, đều được Git ignore. Chỉ công bố mã, hashes và
chỉ số tổng hợp; không commit câu hỏi, gold SQL, database hoặc raw responses.

## Protocol model và scoring

- Qwen3 4B local, digest giữ nguyên; Ollama 0.34.4, temperature=0, seed=42, think=true,
  context=8192 và output cap=4096 mỗi call. Warm-up tách khỏi latency.
- Baseline: một lần sinh và thực thi SQL. Agent LangGraph: tối đa hai lần thử SQL, ba vòng
  tool; model call trả lời cuối vẫn được tính vào token và latency. Thứ tự phương án luân phiên.
- Prompt chỉ có DDL của database tương ứng và quy tắc ngày dùng chung. Không dùng glossary
  thương mại riêng cho benchmark bên ngoài; không có retrieval, chart hoặc clarification tools.
- SELECT SQLite native, connection `mode=ro`, `query_only` và SQLite authorizer. Không đưa
  schema ngoài allowlist thương mại vào guardrail của ứng dụng; lớp chỉ đọc benchmark là riêng.
- Không inject LIMIT hoặc chuyển dialect của predicted/gold SQL. SQL deadline 5 giây,
  resource cap 100.000 dòng: vượt cap là lỗi, không cắt kết quả rồi chấm như đầy đủ.
  Tool chỉ hiển thị 20 dòng preview cho model, scorer so sánh toàn bộ kết quả được đọc.
- Dùng strict/relaxed execution agreement của repo: multiset, giữ thứ tự cột ở strict;
  thứ tự dòng chỉ quan trọng khi gold có ORDER BY ngoài cùng, scalar normalization như suite cũ.
  Khác evaluator chính thức; không gọi là official EX hoặc test-suite accuracy.
- Mọi model miss, SQL error và token cap nằm trong mẫu số của tập đã chọn. Gold invalid
  khi chạy sẽ làm run dừng; không âm thầm loại câu trong lúc inference.
- Ghi thêm metric trên gold không rỗng để nhìn rõ nguy cơ SQL sai cùng trả kết quả rỗng.
  Single-snapshot agreement vẫn có false positives; không chứng minh toàn bộ ngữ nghĩa SQL.

## Chạy và tiếp tục checkpoint

```powershell
# Tải nguồn khi chưa có; thông báo điều kiện sử dụng được in trước tải
.venv/Scripts/python.exe -m eval.datasets.external.download_vitext2sql --accept-license --splits dev test

# Chuẩn bị package mới, không ghi đè package đã tồn tại
.venv/Scripts/python.exe -m eval.harness.prepare_vitext2sql --split dev --output data/external/vitext2sql/packages/dev-new
.venv/Scripts/python.exe -m eval.harness.prepare_vitext2sql --split test --output data/external/vitext2sql/packages/test-new

# Smoke 4 câu dev, chọn cố định seed 42 từ 4 database; không phải kết quả tập lớn
.venv/Scripts/python.exe -m eval.harness.live_vitext2sql --package data/external/vitext2sql/packages/dev-v3 --pilot-size 4 --num-predict 4096

# Toàn bộ 1.618 câu hợp lệ của adapted test; không sample để chọn câu dễ
.venv/Scripts/python.exe -m eval.harness.live_vitext2sql --package data/external/vitext2sql/packages/test-v2 --num-predict 4096

# Nếu bị ngắt: giữ nguyên code/config/package/model, thay run path thật
.venv/Scripts/python.exe -m eval.harness.live_vitext2sql --package data/external/vitext2sql/packages/test-v2 --num-predict 4096 --resume eval/results/<run-vitext2sql-test>
```

Runner ghi `config.json`, `items.jsonl` và `progress.json` sau mỗi prediction; chỉ tạo
`summary.json` khi hoàn tất. Resume giữ các lần sai đã ghi, không chạy lại để chọn đáp án đẹp.
Kiểm tra hashes package/database/code/model options và IDs; từ chối source/config thay đổi,
record trùng hoặc worker thứ hai chạy cùng checkpoint. Không đổi code khi run lớn đang chạy.
Nếu kết quả test được dùng để chỉnh prompt, lượt tiếp theo không còn là đánh giá độc lập
trên tập chưa xem. Phải ghi rõ dev tuning hoặc giữ một test version mới.

## Kiểm thử

**137 passed, 7 skipped** do chưa cấu hình PostgreSQL, 1 cảnh báo LangGraph deprecation;
lint và format đạt, kiểm chứng trước commit ngày 01/10.
Test mới kiểm tra COUNT(*) fast path, CTE, giữ duplicates, chặn DDL/ATTACH/catalog/function,
ghép AST không bỏ qua literal/db_id, pilot cố định, hash thay đổi và khóa checkpoint chống trùng.
Đã kiểm tra baseline dừng khi mất kết nối Ollama và giữ các prediction đã ghi;
kiểm tra riêng đường exception qua agent vẫn cần hoàn tất trước lượt dài.

## Cách ghi CV sau lượt lớn

Chỉ điền XX sau khi `summary.json` của lượt đầy đủ xuất hiện. Ví dụ với toàn bộ package test
hiện tại: “Evaluated a local LangGraph Text-to-SQL agent on 1,618 adapted ViText2SQL questions
across 42 SQLite databases, achieving XX% strict execution agreement.” Không gọi là official
ViText2SQL accuracy hoặc human-reviewed adaptation khi chưa có chứng cứ tương ứng.
