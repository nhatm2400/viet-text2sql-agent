# Kiểm chứng cục bộ và nội dung CV — 29/09/2026

Đây là báo cáo mốc kiểm chứng không dùng LLM, giữ nguyên số liệu lịch sử.
Mốc tiếp theo đã bổ sung seed v2, Ollama local và runner đo model thật;
xem [quy trình live eval](LIVE_LOCAL_EVAL.vi.md). Không dùng các nhận xét
"chưa chạy model" bên dưới để mô tả trạng thái của những mốc sau.

Đã đọc các phần mã nguồn, test, dữ liệu/fixture, cấu hình, tài liệu và deployment trong repo.
Phạm vi chạy lần này: cục bộ, không gọi API, không tải thêm dependency, không triển khai server.
Các nhận xét về deployment bên dưới là đọc mã; không phải kết quả chạy trên VPS.

## 1. Kết quả đã chạy

| Phép kiểm chứng | Kết quả | Ý nghĩa và giới hạn |
|---|---:|---|
| Test trước thay đổi | 93 passed, 7 skipped | Điểm xuất phát; skip đều cần PostgreSQL |
| Test sau thay đổi | 102 passed, 7 skipped | Không có test thất bại; 1 cảnh báo deprecation từ LangGraph |
| SQL policy trong test_ast_policy.py | 38/38 đạt | 28 đầu vào phải chặn, 6 SELECT phải cho qua, 4 kiểm tra LIMIT |
| Test execute_tool_bypass.py | 18/18 đạt | Kiểm tra wrapper không bỏ qua policy; gồm cả positive/audit cases |
| Gold SQL so với đáp án Python | 60/60 khớp strict và relaxed | 30 ca × 2 snapshot, không có LLM |
| Gold SQL sau policy rewrite | 60/60 khớp Python | Rewrite LIMIT giữ nguyên đáp án cho các ca aggregate này |
| SQL cố ý sai vẫn chạy và qua policy | 60/60 | Lỗi ngữ nghĩa không đồng nghĩa với vi phạm SQL safety |
| Bộ chấm phát hiện kết quả cố ý sai | 60/60 | Cả strict và relaxed đều từ chối; không phải model error rate |
| Lint và format toàn repo | Đạt | Ruff check và format --check |
| Smoke fixture cũ | strict 80%, relaxed 100%, 5 ca | Chỉ kiểm tra wiring, tuyệt đối không ghi thành model accuracy |

Nguồn số liệu:

- `eval/results/20260929-124216-294552-local/summary.md`: báo cáo dễ đọc.
- Cùng thư mục: `summary.json` (hash nguồn, hash snapshot, phiên bản runtime), `items.jsonl`
  (từng phép so sánh), `cases.jsonl` (câu hỏi VI/EN, gold SQL và SQL cố ý sửa sai).
- `eval/results/20260929-131004-baseline/summary.md`: smoke fixture, tách riêng.
- Terminal: `.venv/Scripts/python.exe -m pytest -ra` trả `102 passed, 7 skipped`.
- Python 3.12.7, SQLite 3.45.3, sqlglot 26.33.0, SQLAlchemy 2.0.51.

Hai snapshot có **121.002** và **121.464** dòng trên 12 bảng; mỗi snapshot có 5.000 khách,
20.000 đơn. Đây là tổng dòng trên nhiều bảng, không phải số câu hỏi benchmark hoặc số người dùng.
Seed thứ hai có 50.153 dòng order_items; không áp dụng tuyên bố “dưới 50k order_items” cho mọi seed.

30 ca mới là **10 dạng truy vấn × 3 miền**, không phải 30 ý định độc lập hay 60 câu hỏi.
Câu hỏi, SQL và Python oracle đều được tạo với hỗ trợ AI trong phiên làm việc này;
**chưa có người review độc lập**. Không ghi “human-verified benchmark” trên CV.
Đây là tập development với câu hỏi rõ định nghĩa, không phải test set giữ kín.

## 2. Đã xây và sửa gì

- Thêm `eval/datasets/local_dev/cases.py`: 30 cặp câu VI/EN, gold SQL, mutation và metadata nguồn.
- Thêm `oracles.py`: tính đáp án bằng Python, không đọc SQL; tổng tiền dùng integer cents.
- Thêm `eval/harness/local_validation.py`: dựng SQLite trong bộ nhớ, bật foreign keys,
  chuyển query-only sau khi load, chạy SQL thật và xuất báo cáo riêng cho mỗi lần chạy.
- `db/seed.py`: cho phép truyền seed vào `build_rows`; seed mặc định và fixture cũ được giữ.
- Sửa `agent/build.py`: SQL sau thất bại không được kế thừa rows/status của SQL trước thành công.
- Sửa `metrics.py`: nearest-rank percentile dùng ceil; first-pass tính từ lần execute đầu tiên,
  thay vì đánh đồng “không lỗi ở bất cứ lần nào” với “lần đầu thành công”.
- `runner.py` ghi thứ tự trạng thái các lần execute để tính first-pass/recovery chính xác.
  Recovery ở đây vẫn là thành công thực thi; không tự động đồng nghĩa đúng đáp án.
- Sửa `make demo-offline` đang trỏ đến module không tồn tại; thêm `make validate-local`
  và bước validation SQLite trong CI. Cấu hình CI đã sửa, chưa có lượt GitHub Actions mới.
- Thêm 9 regression/integration tests. Không thay implementation retrieval để tạo một claim chưa đo.

## 3. Các phát hiện cần giải quyết trước khi đo model

| Phát hiện | Bằng chứng / trạng thái |
|---|---|
| Retrieval và resolver thời gian chưa hoạt động | `src/t2sql/retrieval/*` là stub; `search_examples` trả not_implemented |
| Ablation chưa phản ánh cấu hình | `runner.py` không truyền model_role vào run_agent; không áp dụng context/example/repair/as_of_date. Baseline YAML ghi fixed_3shot nhưng prompt không có block 3 ví dụ |
| Repair offline là kịch bản | `tests/fixtures/offline_llm.json` định sẵn lần sai và lần sửa; không chứng minh model tự sửa |
| Gold executor online chưa thực sự ép read-only | `live_gold_executor` tạo engine từ URL rồi execute; docstring không phải enforcement |
| Trần hiện tại đếm vòng tools, không đếm từng tool call | `iteration_count` tăng 1 mỗi lần tools_node chạy; một AIMessage có thể chứa nhiều tool_calls. Chưa sửa trong milestone này |
| Số token/cost chưa đo đầy đủ | runner không ghi token usage từ model vào record; avg_tokens không có dữ liệu |
| Scoring có chuẩn hóa mạnh | Chuỗi số được đổi thành số, chuỗi NULL/none thành null; số nguyên đổi float. Cần review nếu áp dụng cho mã định danh hoặc integer lớn |
| Quyền PostgreSQL chưa được xác minh | 7 test read-only bị skip; SQLite query_only không thay cho chứng minh quyền PostgreSQL |
| Deployment chưa được chạy | provision gọi CREATE TABLE không có IF NOT EXISTS nên tuyên bố idempotent cần sửa; script seed sau provisioning cũng cần review ownership/grants |

Một kết quả quan trọng khi chạy diagnostics: seed 20260727 có **13.278/13.279 shipment**
trỏ địa chỉ không thuộc khách của đơn, **1.637 shipment** có delivered_at trước shipped_at,
và **505 review** sau mốc kết thúc snapshot. Seed 20260728 lần lượt có 13.392, 1.575, 499 ca.
Foreign key violations bằng 0 ở cả hai snapshot: khóa ngoại hợp lệ chưa đủ bảo đảm nghiệp vụ đúng.

Không sửa âm thầm generator rồi tiếp tục gọi đó là snapshot cũ. Các ca mới tránh join shipment
qua địa chỉ và tránh giả định về thời điểm shipment/review; khi sửa generator, cần phiên bản mới
và sinh lại fixture. Các kiểm tra này chưa phải kiểm tra mọi quy tắc nhất quán của dữ liệu.

## 4. Trả lời năm câu hỏi

**1. Tiếng Việt thực sự khó đến mức nào khi LLM đã hiểu khá tốt?**

Repo chưa chứng minh tiếng Việt là nút thắt. Khó khăn có thể kiểm tra được ở đây là định nghĩa
KPI, schema và join: doanh thu theo payments.amount/paid_at khác tổng giá trị orders; COUNT dòng
khác SUM số lượng; thiếu DISTINCT làm nhân số. Mutation suite cho thấy những lỗi này tạo đáp án
khác dù SQL vẫn hợp lệ. Nó chưa cho biết LLM mắc những lỗi ấy bao nhiêu lần, hay tiếng Việt khó
hơn tiếng Anh. Định vị nên là “truy vấn analytics bằng tiếng Việt có kiểm chứng”, rồi đo cặp VI–EN
bằng cùng model/schema để xác định ảnh hưởng ngôn ngữ sau.

**2. Dataset tự xây đại diện được bao nhiêu, nguồn ở đâu, có dùng LLM gen không?**

Database là dữ liệu Python mô phỏng. Repo ban đầu có 5 câu seed; lần này thêm riêng 30 ca
development từ 10 template × 3 miền, có câu VI/EN và metadata AI-assisted/human-review-pending.
SQL được thực thi và đối chiếu bằng phép tính Python trên hai seed, nhưng cùng tác giả AI có thể
mắc cùng một hiểu nhầm ở cả hai implementation. Nó có giá trị regression và kiểm tra bộ chấm,
không đại diện doanh nghiệp Việt Nam, không phải benchmark độc lập. Các anomaly về shipment
càng cho thấy phải sửa dữ liệu, duyệt câu hỏi và tách retrieval/dev/test theo family trước khi
tuyên bố khả năng tổng quát. Chưa tải dataset bên ngoài.

**3. Người dùng là ai; filter đủ rồi thì cần agent làm gì?**

Persona thiết kế phù hợp là nhân viên vận hành e-commerce cần câu hỏi phát sinh, biết nghiệp vụ
nhưng không viết SQL thường xuyên. Filter đủ với một bảng đã tổng hợp. Giá trị dự kiến của agent
là tạo bảng đó từ nhiều nguồn: ví dụ khách wholesale nào giảm tiền thực nhận giữa hai quý nhưng
số đơn không giảm. Đây là ví dụ workflow cần phát triển và đánh giá, chưa phải tính năng đã đo
thành công hoặc nhu cầu thị trường đã xác thực.

**4. Workflow nào tốt hơn spreadsheet/dashboard/BI/analyst?**

Chưa có bằng chứng “tốt hơn”. Phạm vi nên thử là câu hỏi ad-hoc có join/aggregate và điều kiện
thay đổi, trả SQL + bảng + định nghĩa phép tính để kiểm tra. Dashboard vẫn phù hợp KPI lặp lại;
analyst vẫn cần cho suy luận nguyên nhân. Mốc so sánh đầu nên là cùng LLM sinh SQL một lượt,
rồi thêm retrieval và sửa lỗi từng yếu tố. Hiện chưa chạy model, chưa có RAG/agentic uplift.
Milestone này chứng minh công cụ kiểm chứng được một số lỗi ngữ nghĩa, không chứng minh thay BI.

**5. Giá trị kinh doanh đủ để triển khai và duy trì không?**

Chưa biết. Giá trị portfolio đã rõ hơn: có loop, policy, bộ chấm, SQL execution thực và báo cáo
có thể tái lập. Giá trị doanh nghiệp cần đo tỷ lệ câu hỏi trả đúng sau kiểm tra, thời gian xử lý
bao gồm công review, tần suất nhu cầu, chi phí model và chi phí bảo trì schema/KPI. Chưa có số
tiết kiệm thời gian, ROI, latency LLM hoặc chi phí trên truy vấn để đưa vào CV.

## 5. CV có thể dùng ngay

Giữ `In Development`. Bản 3 bullet dưới đây giữ phần agent trung tâm và dùng các số đã chạy:

```latex
\resumeSubheading
  {\href{https://github.com/nhatm2400/viet-text2sql-agent}{Viet-Text-to-SQL Agent -- Vietnamese Database Analytics}}{}
  {AI Engineer}{In Development}
  \resumeItemListStart
    \resumeItemPlain{Built a LangGraph Text-to-SQL agent prototype for a 12-table PostgreSQL schema, with Vietnamese business-term lookup, SQL AST validation, and clarification handling.}
    \resumeItemPlain{Built a 30-case SQL validation suite across 10 query families and two synthetic SQLite snapshots; all 60 gold-query checks matched Python reference calculations, and both execution scorers rejected all 60 deliberately incorrect query results.}
    \resumeItemPlain{Validated SQL guardrails with 38 passing policy tests and 18 passing execution-wrapper tests, covering rejected inputs, permitted queries, LIMIT enforcement, and validation-bypass attempts.}
  \resumeItemListEnd
```

Nếu chỉ đủ chỗ cho 2 bullet, giữ bullet agent và bullet 30-case; số 38/18 có thể để README.
Không viết “achieved 100% Text-to-SQL accuracy”, “improved accuracy with RAG”,
“human-verified benchmark”, “production-ready”, hoặc “PostgreSQL security verified” từ lần chạy này.

## 6. Tái lập và bước tiếp theo

Tại thư mục gốc repo:

```powershell
.venv/Scripts/python.exe -m eval.harness.local_validation
.venv/Scripts/python.exe -m pytest -ra
.venv/Scripts/python.exe -m eval.harness.runner --config eval/configs/baseline.yaml --offline
.venv/Scripts/ruff.exe check .
.venv/Scripts/ruff.exe format --check .
```

Không cần chạy db/seed.py để dùng validation mới; database trong bộ nhớ được tạo riêng.
Raw results vẫn git-ignored. Chưa commit/push thay đổi trong lần làm việc này.

Thứ tự phát triển tiếp: sửa generator và version snapshot; con người review định nghĩa/gold;
thiết kế test set theo query family giữ riêng; nối và test cấu hình baseline/ablation;
chạy model thật khi có ngân sách; sau đó mới đo đóng góp retrieval/repair và VI–EN.
Không cần mở rộng hạ tầng để có thêm những con số kiểm chứng cục bộ hiện tại.
