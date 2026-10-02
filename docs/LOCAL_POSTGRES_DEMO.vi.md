# Demo Qwen local + PostgreSQL thật - 02/10/2026

Đã nối provider `ollama_local` vào factory dùng chung của LangGraph, FastAPI và Streamlit.
Không cần API key hay SDK nhà cung cấp. Profile demo riêng nằm trong
`data/postgres_local/demo.env`, bị Git ignore; chế độ offline mặc định của repo vẫn dùng fixtures.

PostgreSQL **17.11** portable chạy tại `127.0.0.1:55432`, database `t2sql`, role truy vấn
`t2sql_ro`. Có **12 bảng nghiệp vụ**, seed v2 với 5.000 customers, 20.000 orders và
49.792 order_items. Tracing dùng bảng `agent_traces` riêng; role truy vấn không được đọc
bảng đó. Dữ liệu, credentials, binaries và logs chỉ nằm trong `data/postgres_local/`.

Nguồn ZIP là bản Windows x64 do [EDB cung cấp](https://www.enterprisedb.com/download-postgresql-binaries),
được [trang PostgreSQL chính thức dẫn tới](https://www.postgresql.org/download/windows/).
SHA256 cục bộ: `80379b2c04d51c30225532e0ae04509899141e9957ed096fe749d7fd9df8f82f`.
Đây là hash ghi nhận của file đã tải, không phải chữ ký/checksum độc lập do nhà cung cấp xác nhận.

## Mở demo trên máy hiện tại

UI: **http://127.0.0.1:8501**, API docs: **http://127.0.0.1:8000/docs**.
Nếu tiến trình hiện tại còn chạy, mở các địa chỉ này trực tiếp. Sau khi restart máy:

```powershell
cd E:/FPTU/PRJ/viet-text2sql
# Khởi động lại cluster nếu đã dừng; không drop/reseed database hiện có.
.venv/Scripts/python.exe -m scripts.setup_postgres_local

# Chỉ chạy nếu Ollama chưa có server ở 11434; giữ terminal này mở.
$env:OLLAMA_MODELS = (Resolve-Path data/ollama_local/models).Path
$env:OLLAMA_HOST = '127.0.0.1:11434'
$env:OLLAMA_NO_CLOUD = '1'
$env:OLLAMA_NUM_PARALLEL = '1'
& ./data/ollama_local/runtime/ollama.exe serve
```

Mở hai terminal khác, tại repo:

```powershell
.venv/Scripts/python.exe -m scripts.run_local_demo api
```

```powershell
.venv/Scripts/python.exe -m scripts.run_local_demo ui
```

Wrapper UI gọi `streamlit run` đúng cách. Không chạy trực tiếp
`python ui/streamlit_app.py`, vì cách đó thiếu runtime Streamlit. Dừng API/UI foreground
bằng Ctrl+C. Dừng PostgreSQL bằng:

```powershell
& ./data/postgres_local/runtime/pgsql/bin/pg_ctl.exe -D ./data/postgres_local/cluster -w stop -m fast
```

## Cài từ checkout mới trên Windows

Cần venv của repo và Qwen3 4B trong Ollama; có thể dùng `scripts/setup_ollama_local.ps1`
khi thư mục runtime chưa tồn tại. Tải PostgreSQL vào thư mục ignored rồi chạy setup:

```powershell
New-Item -ItemType Directory -Force data/postgres_local | Out-Null
Invoke-WebRequest 'https://sbp.enterprisedb.com/getfile.jsp?fileid=1260616' -OutFile data/postgres_local/postgresql-17.11-windows-x64.zip
.venv/Scripts/python.exe -m scripts.setup_postgres_local
```

Setup khởi tạo cluster mới với SCRAM, bind loopback và port 55432; tạo mật khẩu ngẫu
nhiên vào private profile, seed v2 trên database trống, tạo trace và áp dụng `db/roles.sql`.
Không đặt mật khẩu trong command line. Đây là script Windows, không cài service hoặc sửa PATH.

## Bằng chứng kiểm chứng

Full regression trên máy ngày 02/10: **182 passed, 0 failed, 0 skipped** (17,38 giây),
gồm **11 kiểm tra PostgreSQL thật**; ruff check và format đạt trên 75 file Python.
Model trong tests là fixtures; live model requests được kiểm chứng riêng bên dưới.
Report JUnit cục bộ: `data/postgres_local/tests.xml`.

GitHub CI đã pass lint/test/security trên commit demo. Job deploy VPS từng lỗi tại bước
`Deploy and verify`; việc triển khai từ nay chỉ chạy khi Actions variable
`DEPLOY_ENABLED=true` và đã cấu hình các SSH/VPS secrets. Demo local không cần VPS.

[API demo và tool traces](evidence/local-postgres-demo-20261002.json): câu đếm orders tháng
6/2026 trả **2.351**, khớp truy vấn reference; câu “khách hàng active” gọi glossary rồi
ask_clarification; yêu cầu DROP được Qwen từ chối mà không thực thi SQL. Câu trả lời
không chạy SQL có trạng thái `answered`, không được coi là policy block hay query thành công.
Probe riêng gọi `execute('DROP TABLE customers')` trả `blocked`; số customers trước/sau
giữ 5.000. Đây là kiểm tra demo, không phải benchmark accuracy hay chứng minh mọi prompt
injection đều bị model từ chối.

Đã kiểm chứng quyền database trực tiếp: SELECT được phép; INSERT/UPDATE/DELETE/CREATE
bị chặn; ghi vẫn bị từ chối khi tắt mặc định read-only; bảng trace không được đọc;
query `pg_sleep(6)` bị server hủy sau giới hạn 5 giây. Session timeout riêng của executor
được kiểm tra qua hai lần checkout pool và query thực ở mức 100ms.

```powershell
.venv/Scripts/python.exe -m scripts.run_local_demo test-db
.venv/Scripts/python.exe -m scripts.run_local_demo test-all
.venv/Scripts/python.exe -m scripts.check_local_demo
.venv/Scripts/python.exe -m scripts.check_local_demo --ui-only
```

Hai lệnh test dùng model fixtures và không gọi LLM; hai lệnh demo gọi Qwen local thật.
Evidence UI dùng runtime Streamlit AppTest, không thay cho review hình ảnh trên trình duyệt.
[Kết quả UI thật](evidence/local-postgres-ui-20261002.json): một câu đếm orders trả đúng
2.351, gọi get_table_schema rồi execute_sql, không có exception; latency 122,36 giây.

## Giữ riêng benchmark

61,0%/72,6% trên 500 câu được đo ở các database SQLite Spider. Không chuyển các điểm
này thành accuracy PostgreSQL của demo. Source app đã thay đổi sau mốc 500; muốn resume
run cũ phải dùng snapshots/environment tương thích. Không sửa hashes để bỏ kiểm tra.
Tối ưu tiếp dùng development và test mới giữ riêng.
