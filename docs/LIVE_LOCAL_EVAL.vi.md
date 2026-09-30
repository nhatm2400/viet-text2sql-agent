# Đo model thật trên máy local

[Kết quả mới nhất](DATE_WINDOW_RESULTS.vi.md): 80% baseline và 80% agent trên 20 câu dev,
với CHECK constraints, quy tắc khoảng ngày và output cap 4096.

Mốc này dùng SQLite native SQL trên schema 12 bảng. Đây không phải phép đo PostgreSQL hoặc RAG.
Mô hình chạy bằng Ollama localhost; adapter từ chối URL ngoài loopback và model cloud.
Không dùng API key, không có phí API; điện năng và khấu hao phần cứng chưa được đo.

## Môi trường và cài đặt

Máy kiểm tra có NVIDIA RTX 4050 Laptop với 6.141 MiB VRAM.
Model khởi đầu: `qwen3:4b`, khoảng 2,5 GB theo [Ollama model page](https://ollama.com/library/qwen3:4b).
Lựa chọn này nhằm chạy được trên phần cứng hiện có, không phải khẳng định model tốt nhất.
Ollama hỗ trợ Windows và CLI portable theo [tài liệu chính thức](https://docs.ollama.com/windows).

Script `scripts/setup_ollama_local.ps1` cần sự đồng ý riêng trước khi chạy: tải runtime chính thức,
kiểm tra SHA-256 GitHub release, giải nén vào `data/ollama_local`, bật server chỉ ở
`127.0.0.1:11434`, tắt cloud, tải model. Không thay PATH hệ thống. Không chạy lại script nếu đã cài;
bản cài đã có `installation.json`, log server và model cache trong thư mục đó.

Khởi động lại runtime đã cài trong PowerShell nếu server đang tắt:

```powershell
$env:OLLAMA_MODELS = (Resolve-Path data/ollama_local/models).Path
$env:OLLAMA_HOST = '127.0.0.1:11434'
$env:OLLAMA_NO_CLOUD = '1'
$env:OLLAMA_NUM_PARALLEL = '1'
& ./data/ollama_local/runtime/ollama.exe serve
```

## Snapshot và bộ câu hỏi

`build_rows(version="v2")` sửa dữ liệu theo quy tắc đã công bố:

- Shipment trỏ đến địa chỉ mặc định của đúng khách của đơn.
- Thời gian: đặt đơn ≤ thanh toán ≤ gửi hàng ≤ giao hàng ≤ mốc snapshot.
- Sản phẩm tồn tại không muộn hơn lần xuất hiện đầu tiên trong đơn.
- Review chỉ được giữ nếu khách đã có giao dịch completed cho sản phẩm, và thời gian review
  nằm từ lần hoàn tất sớm nhất đến mốc kết thúc snapshot. ID review có thể không liên tục.
- v1 vẫn là mặc định để giữ kết quả fixture cũ. Không ghi đè `data/dev.sqlite`.

Gói dùng hiện tại: `data/benchmark_v2_ready/` (candidate-3):

- `snapshot.sqlite`: snapshot v2 cố định, có index phục vụ các join/EXISTS.
- `questions.json`: 20 câu dev từ 10 family × 2 miền, 30 câu test candidate.
- `REVIEW.md`: câu hỏi, gold SQL, cột kết quả và tối đa 10 dòng preview.
- `manifest.json`: phiên bản, hash, số dòng và diagnostics.

Hai thư mục trước đó (`benchmark_v2`, `benchmark_v2_review`) là các bản chuẩn bị thất bại do
SQL thời gian không tương thích dialect; được giữ để truy nguyên, không dùng cho eval.
Không phải mọi SQL PostgreSQL đều chuyển chính xác bằng sqlglot phiên bản hiện có. Vì vậy phép
đo mới yêu cầu cả model và gold dùng SQLite native, và không diễn giải lỗi chuyển dialect thành
lỗi hiểu câu hỏi của model. Policy vẫn là policy PostgreSQL của ứng dụng; khác biệt dialect
có thể ảnh hưởng tỷ lệ bị chặn và cần đánh giá riêng trước khi áp dụng cho PostgreSQL.

Tạo gói mới (lệnh từ chối ghi đè thư mục đã tồn tại):

```powershell
.venv/Scripts/python.exe -m eval.harness.prepare_v2 --package data/benchmark_v2_new
```

Đây là câu hỏi và gold SQL được AI hỗ trợ tạo. Thực thi thành công không đồng nghĩa nhãn đúng.
20 câu dev không phải 20 ý định độc lập. Test candidate cần review thêm mức đa dạng/overlap;
không khẳng định generalization sang schema, doanh nghiệp hoặc query family chưa từng thấy.

## Chạy model thật

```powershell
# Smoke model thật trên 2 câu dev, không dùng để chọn kết quả đẹp nhất
.venv/Scripts/python.exe -m eval.harness.live_local --split dev --limit 2

# Chạy toàn bộ 20 câu development, cả baseline và agent
.venv/Scripts/python.exe -m eval.harness.live_local --split dev

# Pilot tái lập mốc ngân sách cũ, context chưa có CHECK
.venv/Scripts/python.exe -m eval.harness.live_local --split dev --num-predict 4096 --schema-context types-and-fks --date-windows unchanged --ids cancelled_orders_north revenue_q2_north units_2026_north sold_categories_north

# Đo đầy đủ để so sánh ngân sách; không gộp pilot vào mẫu số 20 câu
.venv/Scripts/python.exe -m eval.harness.live_local --split dev --num-predict 4096 --schema-context types-and-fks --date-windows unchanged

# Tái lập thí nghiệm CHECK constraints, giữ output cap 4096
.venv/Scripts/python.exe -m eval.harness.live_local --split dev --num-predict 4096 --schema-context with-checks --date-windows unchanged

# Thí nghiệm khoảng ngày: thêm quy tắc [start, end), giữ CHECK và output cap 4096
.venv/Scripts/python.exe -m eval.harness.live_local --split dev --num-predict 4096 --schema-context with-checks --date-windows half-open
```

Hai phương án dùng cùng model digest, schema, glossary, snapshot, temperature=0,
seed=42, context=8192, output cap=2048, thinking=true:

`--num-predict` thay đổi output cap **mỗi lần gọi model**, gồm cả reasoning; không phải
tổng token cho toàn câu hỏi. Runner ghi giá trị thực vào config. `--ids` chỉ dùng cho dev,
giữ thứ tự câu trong dataset và không dùng cùng --limit. Test vẫn phải chạy đầy đủ.

`--schema-context with-checks` (mặc định hiện tại) thêm các CHECK predicate từ DDL vào
prompt và get_table_schema. `types-and-fks` giữ context trước thay đổi để tái lập mốc cũ.
So sánh schema dùng `compare_local --axis schema-checks`, yêu cầu cùng mọi model option
và chỉ cho phép thêm các dòng CHECK; không gộp việc đổi token với việc đổi schema context.

`--date-windows half-open` (mặc định hiện tại) thêm quy tắc chung cho khoảng ngày trên
cột timestamp: `>= start AND < exclusive_end`, gồm toàn bộ ngày cuối kỳ. Quy tắc được
dùng chung với system prompt của ứng dụng; không chứa câu hỏi hoặc đáp án benchmark.
So sánh riêng thay đổi này dùng `compare_local --axis date-windows`, yêu cầu context
chỉ nối thêm đúng quy tắc và mọi model option giữ nguyên. `--date-windows unchanged`
giữ context của các thí nghiệm cũ. Quy tắc giữ nguyên điều kiện giờ cụ thể và ngưỡng
thời lượng khi câu hỏi yêu cầu; không sửa SQL do model sinh bằng postprocessing.

Muốn so sánh hai run đầy đủ, dùng exporter (từ chối run thiếu câu hoặc khác model/prompt/data):

```powershell
.venv/Scripts/python.exe -m eval.harness.compare_local --before eval/results/<run-2048> --after eval/results/<run-4096> --output docs/evidence/<comparison>.json
```

Exporter ghi số câu đúng, ca hết token, latency, token và ID cải thiện/giảm điểm. Một lượt
mỗi cấu hình là mốc development; không chọn lượt đẹp nhất và không suy diễn kiểm định
nhân quả từ biến thiên latency giữa hai ngày đo.

Lượt smoke đầu (`20260929-175919-126877-live-local-dev`) dùng `think=false` đã gặp
phần suy luận lẫn vào `message.content`, khiến baseline không nhận được SQL thuần.
Cấu hình hiện tại dùng `think=true` để Ollama tách `message.thinking` và `message.content`
theo [API chính thức](https://docs.ollama.com/capabilities/thinking). Adapter chỉ dùng
content/tool_calls, giữ nguyên phản hồi gốc trong log. Token và latency vẫn bao gồm
phần suy luận. Lượt smoke lỗi được giữ lại; không gộp với kết quả cấu hình đã sửa.

- Baseline: một lần sinh SQL, một lần thực thi.
- Agent: LangGraph với tool execute_sql, tối đa hai lần thử SQL; tối đa ba vòng tools.
  Ngân sách SQL được khóa ở tool, kể cả khi model đề nghị nhiều tool call trong một lượt.
  Phiên bản eval này không có retrieval, chart hay clarification tools; không gọi nó là
  kết quả của toàn bộ cấu hình production/UI.

Một warm-up được ghi riêng và loại khỏi latency của hai phương án. Thứ tự baseline/agent
đảo luân phiên theo câu để giảm lợi thế do thứ tự. Thời gian gồm gọi model và thực thi SQL;
không gồm tạo snapshot hoặc chạy gold. Chỉ số p95 với 20 câu vẫn là ước lượng rất nhỏ.
So sánh này đo toàn bộ hai chiến lược, không cô lập tác dụng của repair.

Mỗi run lưu `config.json`, `items.jsonl`, `summary.json`, `summary.md` vào `eval/results/`.
Có model digest, runtime version, câu trả lời model, SQL, lần thử, token counts, lỗi,
latency, strict/relaxed, hash snapshot/câu hỏi/mã nguồn. Các ca lỗi được giữ trong mẫu số.
Không tự thay kết quả lỗi bằng fixture và không tự tải model trong runner.
Nếu bật `--repeats 3`, các lượt lặp không phải câu hỏi độc lập mới.

## “Review” nghĩa là gì?

Nếu chưa có công cụ SQL, mở trang xem dữ liệu bằng thư viện đã có trong repo:

```powershell
.venv/Scripts/python.exe -m streamlit run ui/database_review.py --server.address 127.0.0.1 --server.port 8502 --server.headless true --browser.gatherUsageStats false
```

Truy cập `http://127.0.0.1:8502`. Tab **Xem bảng** cho chọn bảng và xem 100 dòng đầu;
**Xem đáp án mẫu** cho chọn câu hỏi rồi chạy gold SQL; **Tự chạy SELECT** có sẵn truy vấn
đếm khách theo miền/trạng thái để đối chiếu. Mỗi kết quả truy vấn hiển thị tối đa 500 dòng.
Trang chỉ đọc snapshot, không gọi model và không tự cập nhật trạng thái review.

Không phải xác nhận cho phép chạy chương trình. Review là kiểm tra đáp án chuẩn có đúng ý không:

1. Đọc câu hỏi: “tiền thanh toán succeeded quý 2 theo paid_at”.
2. Kiểm tra SQL dùng `payments.amount`, lọc `status='succeeded'`, khoảng ngày `[01/04,01/07)`.
3. Kiểm tra join có đếm tiền nhiều lần không, và đơn vị/rounding/các cột trả về có đúng không.
4. Đánh dấu chỗ chưa rõ hoặc sửa gold. Kết quả preview chỉ giúp phát hiện bất thường, không tự
   chứng minh định nghĩa nghiệp vụ đúng. Các đáp án rỗng cần kiểm tra thêm để tránh false positive.

Có thể bắt đầu bằng 5 câu mỗi lần. Nếu chưa tự review SQL được, nhờ một người hiểu SQL cùng
kiểm tra; không nhờ AI tự gắn nhãn “human-reviewed”. Khi một người thực sự duyệt từng câu,
cập nhật `human_review` thành `approved` và `reviewer` thành tên/định danh người đó trong
`questions.json`. Không bulk-approve chỉ vì cả 50 SQL đều chạy được.

```powershell
.venv/Scripts/python.exe -m eval.harness.prepare_v2 --package data/benchmark_v2_ready --freeze
.venv/Scripts/python.exe -m eval.harness.live_local --split test
```

Freeze yêu cầu đủ 20 dev/30 test, mỗi câu có người review, snapshot không thay đổi và gold
thực thi được. Run test kiểm tra hash câu hỏi sau freeze và không cho chọn vài câu bằng --limit.
Sau khi xem kết quả test, không tối ưu trên test rồi vẫn gọi nó là held-out; muốn phát triển tiếp
thì giữ kết quả mốc cũ và chuẩn bị tập test mới.

Trong khi chưa review, cách gọi đúng là **preliminary development execution accuracy on
AI-authored synthetic questions**. Không đổi nhãn thành “official” hoặc “human-verified”.
