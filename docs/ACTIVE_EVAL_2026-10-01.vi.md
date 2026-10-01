# Agent eval — checkpoint từ 01/10/2026

**Sau mốc 500:** ngày 02/10 code app/provider được phát triển thêm cho demo PostgreSQL.
Checkout hiện tại khác source snapshots của run; runner sẽ từ chối resume cùng checkpoint.
Các lệnh resume dưới đây là lịch sử, chỉ dùng với đúng source/environment đã đóng băng.
Không sửa hash để vượt kiểm tra. Report prefix vẫn replay được vì kiểm chứng snapshots
của run. Sau khi phân tích lỗi, tối ưu trên development và đánh giá bằng tập mới giữ riêng.

**Trạng thái hiện tại (02/10):** đã tự dừng ở **đúng 500/1.618 câu** theo yêu cầu;
worker đã thoát, 500 predictions không trùng ID/variant. Strict **305/500 = 61,0%**,
relaxed **363/500 = 72,6%** trên source-order prefix, 15 database và 332 cặp database–SQL AST.
Đã replay scoring và kiểm tra hashes; kết quả/câu CV:
[EVAL_500_RESULTS.vi.md](EVAL_500_RESULTS.vi.md). Còn 1.118 câu; không tự tiếp tục.
Helper/log phiên cutoff: `eval/results/to-500-20261001-165904-721888/`.
Tập 1.618 câu vẫn chưa hoàn tất; không gọi kết quả prefix là accuracy toàn tập.

**Snapshot lần tạm dừng gần nhất:** đã tạm dừng theo yêu cầu người dùng ở **490/1.618 câu**, còn
**1.128 câu**. Worker đã thoát; log xác nhận `Paused: 490/1618 predictions saved`.
Đã kiểm tra 490 predictions không trùng ID/variant. Strict tạm thời **303/490 = 61,84%**,
relaxed **361/490 = 73,67%**; chưa có kết quả toàn tập. Lần sau dùng lệnh resume bên dưới.

**Phiên vừa dừng:** đã resume lúc **20:12 ngày 01/10** từ checkpoint **302 câu**,
giữ nguyên code, model, package và cấu hình. Launcher PID: `12648`, worker PID: `11572`;
đã xác nhận 302 câu cũ giữ nguyên và checkpoint đã ghi tiếp câu 303. Log và metadata:
`eval/results/resume-agent-20261001-131222-796234/`. Phiên này có ngân sách 5 tiếng,
ngừng nhận câu mới khoảng **01:12 ngày 02/10** hoặc khi người dùng yêu cầu dừng sớm.
Tiến độ mới nhất đọc từ `progress.json`; các số bên dưới là snapshot lịch sử.

**Snapshot lần tạm dừng trước:** đã tạm dừng theo yêu cầu người dùng ở **302/1.618 câu**, còn
**1.316 câu**. Worker đã thoát; log xác nhận `Paused: 302/1618 predictions saved`.
Đã kiểm tra 302 predictions không trùng ID/variant. Strict tạm thời **209/302 = 69,21%**,
relaxed **237/302 = 78,48%**; chưa có kết quả toàn tập. Lần sau dùng lệnh resume bên dưới.

**Phiên trước:** đã resume lúc **14:18 ngày 01/10** từ checkpoint 124 câu,
giữ nguyên code, model và cấu hình. Launcher PID phiên mới: `5888`, worker PID: `18456`;
log và metadata:
`eval/results/resume-agent-20261001-071808-334719/`. Phiên mới có ngân sách 5 tiếng,
ngừng nhận câu mới khoảng 19:18 hoặc khi người dùng yêu cầu dừng sớm. Tiến độ hiện tại
đọc từ `progress.json`, không dùng số liệu snapshot bên dưới làm kết quả mới nhất.

**Snapshot lần tạm dừng trước:** đã tạm dừng theo yêu cầu người dùng, worker đã thoát và log
xác nhận `Paused: 124/1618 predictions saved`. Checkpoint giữ **124 câu**, còn **1.494 câu**.
Strict tạm thời **101/124 = 81,45%**, relaxed **106/124 = 85,48%**. Chưa có `summary.json`;
đây là progress trên prefix đã chạy, không phải kết quả toàn tập. Tiếp tục bằng đúng lệnh
resume bên dưới; không tạo run mới hoặc chạy lại các câu đã ghi.

Khởi động lúc **10:05 giờ Việt Nam/Bangkok ngày 01/10**, theo yêu cầu tiếp tục của người dùng.
Qwen3 4B local, agent trên đủ **1.618 câu hợp lệ / 42 database** của adapted ViText2SQL test-v2.
Không dùng API trả phí. Đây không phải điểm leaderboard ViText2SQL/Spider chính thức.

## Checkpoint và tiến trình lịch sử

- Run: `eval/results/20261001-030508-057723-vitext2sql-test/`.
- Launcher PID: `5096`; Python worker PID ban đầu: `20632`.
- Log và metadata: `eval/results/launch-agent-20261001-030505-702588/`.
- Cấu hình: `config.json`; kết quả từng câu: `items.jsonl`; tiến độ: `progress.json`.
- Source snapshot và hashes của 13 file đã kiểm tra; runtime Python/SQLite/thư viện đã lưu.
- `summary.json` chỉ có khi đủ 1.618 predictions. Khi chưa xong, điểm chỉ là progress.

Phiên này có ngân sách **18.000 giây (5 tiếng)**, tính từ khi bắt đầu runner. Sau mốc đó
runner không nhận câu mới; câu đang xử lý được hoàn tất và lưu trước khi dừng. Người dùng
có thể yêu cầu dừng sớm sau khoảng 2 tiếng. Không đổi code, model, package, prompt hoặc
ngân sách suy luận giữa các phiên của cùng run.

## Dừng an toàn

Gửi “dừng eval” trong chat để trợ lý đặt tín hiệu dừng; hoặc chạy lệnh này từ repo:

```powershell
Set-Content -LiteralPath 'E:/FPTU/PRJ/viet-text2sql/eval/results/20261001-030508-057723-vitext2sql-test/pause.request' -Value 'pause' -Encoding utf8
```

Runner hoàn tất và fsync câu hiện tại rồi dừng trước câu tiếp theo. Nếu Ollama bị tắt,
timeout hoặc tiến trình bị ngắt đột ngột, các câu đã ghi vẫn giữ nguyên; câu chưa ghi sẽ
được chạy lại. Trước khi resume, xác nhận worker cũ đã dừng; run lock chặn worker trùng.

## Tiếp tục

```powershell
.venv/Scripts/python.exe -m eval.harness.live_vitext2sql --package data/external/vitext2sql/packages/test-v2 --variant agent --num-predict 4096 --max-wall-seconds 18000 --resume eval/results/20261001-030508-057723-vitext2sql-test
```

Resume tương thích sẽ xóa tín hiệu pause cũ, giữ cả đúng/sai đã ghi và chỉ chạy phần còn
thiếu. Nếu Ollama đã tắt, khởi động lại runtime local với cùng model path trước resume.
Không chạy lại câu sai để chọn câu trả lời tốt hơn. PID và log của phiên mới phải lưu lại.

## Bằng chứng trước chạy

- **158 passed, 7 skipped** vì chưa cấu hình PostgreSQL; lint/format đạt.
- Kiểm chứng mất kết nối/timeout cả baseline và agent, checkpoint/resume, pause và ngân sách phiên.
- Đã xuất [pilot tổng hợp](evidence/vitext2sql-dev-pilot-20261001.json), replay SQL và scoring:
  baseline 2/4, agent 3/4. Pilot không dự báo accuracy toàn tập.
- 42 database có hashes đúng. 1.618 câu gồm 1.004 cặp database–SQL AST khác nhau;
  174 gold trả rỗng. 290 câu không hợp lệ được loại trước inference, đã lưu ledger.
- Chưa có independent human sample audit; không gọi bản thích nghi là human-reviewed.

Khi hoàn tất, replay evidence và xuất report tổng hợp bằng `eval.harness.report_vitext2sql`.
Raw questions, SQL, database và responses vẫn chỉ nằm trong thư mục Git ignore.
