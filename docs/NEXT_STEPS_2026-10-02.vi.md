# Kế hoạch ngày 02/10/2026

**Đã làm thêm ngày 02/10 theo yêu cầu làm đủ bốn phần:**

- README cập nhật **61,0% strict / 72,6% relaxed trên 500 câu, 15 database**, links evidence
  và giới hạn adapted prefix; bỏ khẳng định human review chưa được xác nhận.
- Native `ollama_local` dùng chung cho UI/API; PostgreSQL portable 17.11 trên loopback
  55432, dữ liệu synthetic v2 12 bảng. SELECT, clarification và từ chối DROP đã chạy qua
  API thật; Streamlit runtime cũng trả đúng 2.351 orders. [Demo](LOCAL_POSTGRES_DEMO.vi.md).
- Full regression **182 passed, 0 skipped**, gồm 11 role/timeout kiểm tra trên PostgreSQL
  thật; lint/format đạt. Sửa SET session timeout để không mất khi pool rollback khởi tạo.
- Replay và phân loại đủ **195 strict misses**; chi tiết có giấy phép hạn chế ở thư mục
  ignored, chỉ aggregate đưa vào Git. [Phân tích](ERROR_ANALYSIS_500.vi.md).

Eval vẫn dừng ở 500. Code app mới khác frozen source của run; không resume bằng checkout
mới hay sửa hash. Task tiếp theo là tối ưu trên development và đánh giá tập mới giữ riêng,
cùng independent human sample audit khi có người review. Nội dung kế hoạch phía dưới là
**lịch sử trước khi chốt 500**, không phải danh sách việc còn phải thực hiện hôm nay.

**Cập nhật 02/10:** người dùng yêu cầu chạy tới khoảng 500 câu rồi dừng để
chốt báo cáo kết quả. Đã dừng ở đúng 500, worker thoát; replay xác nhận **61,0% strict**,
**72,6% relaxed**, 15 database và 332 cặp database-SQL AST. Báo cáo kết quả đã lưu tại
[EVAL_500_RESULTS.vi.md](EVAL_500_RESULTS.vi.md). Không tự tiếp tục 1.118 câu còn lại.

**Cập nhật 01/10:** runner đã kiểm chứng; agent đã tạm dừng ở **124/1.618 câu**, sau đó
resume lúc **14:18**, rồi tạm dừng theo yêu cầu ở **302/1.618 câu**; worker đã thoát,
checkpoint giữ nguyên. Đã resume lại lúc **20:12** từ 302 câu với phiên tối đa 5 tiếng,
không đổi cấu hình; sau đó tạm dừng theo yêu cầu ở **490/1.618 câu**, còn **1.128 câu**,
worker đã thoát và checkpoint được giữ.
Trạng thái/đường dẫn resume:
[ACTIVE_EVAL_2026-10-01.vi.md](ACTIVE_EVAL_2026-10-01.vi.md). Nội dung dưới là kế hoạch
và snapshot lúc tạm dừng trước đó.

Task được tạm dừng theo yêu cầu người dùng ngày 01/10. Không có tiến trình live eval
của repo đang chạy; chưa khởi động lượt model trên adapted test split.

## Trạng thái đã có

- Đã tích hợp downloader có version/hash, preflight nhiều database và runner checkpoint.
- Package dev-v3: 898 câu hợp lệ / 25 database, từ 954 câu nguồn.
- Package test-v2: 1.618 câu hợp lệ / 42 database, từ 1.908 câu nguồn;
  1.004 cặp database-SQL AST khác nhau. Danh sách 290 câu loại trừ đã lưu riêng.
- Pilot cố định 4 câu dev / 4 database: baseline 2/4, agent 3/4. Các model misses đều
  hết output cap 4096 trước khi xuất SQL; không sửa prompt hoặc chọn lại mẫu sau kết quả.
- Pilot hoàn tất tại `eval/results/20260930-180012-955024-vitext2sql-dev/`;
  có summary, raw outputs, config và source snapshot đã kiểm tra hashes.
- Kiểm chứng trước commit ngày 01/10: full regression **137 passed, 7 skipped** do chưa
  cấu hình PostgreSQL; lint và format đạt. Đã kiểm tra fail-fast baseline khi mất kết nối,
  fsync checkpoint và 60 cặp case/snapshot cục bộ, không gọi LLM.
  Kiểm tra riêng fail-fast qua agent vẫn nằm trong kế hoạch ngày mai.

## Thứ tự thực hiện ngày mai

1. **Chốt độ ổn định runner trước lượt dài.** Chạy lại tests tập trung rồi full regression
   và lint. Kiểm tra mất kết nối/timeout ở cả baseline và agent, bao gồm cách run_agent
   xử lý exception: sự cố Ollama phải dừng run và giữ checkpoint, không biến các câu
   chưa chạy thành hàng loạt model misses. Kiểm tra resume không chạy lại prediction
   đã ghi, không nhận code/config/database khác và không cho worker trùng.
2. **Chốt protocol và bằng chứng.** Kiểm tra ngữ nghĩa các câu pilot, ghi đúng loại review
   thực hiện; không gắn human-reviewed nếu chưa có người review. Xuất report tổng hợp
   cho pilot với hashes, source/eligible counts và exclusions; không đưa câu hỏi, SQL,
   database hay raw responses ViText2SQL vào Git. Lưu source/config cố định cho lượt lớn.
3. **Khởi động agent trên đủ 1.618 câu adapted test hợp lệ.** Qwen3 4B local, output
   cap 4096, cùng protocol đã chốt. Chạy agent trước để đo execution accuracy; baseline
   trên tập lớn có thể là lượt so sánh riêng sau đó. Không sample câu dễ hoặc đổi cap
   giữa lượt. Theo pilot, agent có thể cần khoảng 25 giờ; đây chỉ là ước lượng từ 4 câu.
4. **Theo dõi và báo cáo đúng trạng thái.** Ghi PID, đường dẫn run/log, checkpoint và
   câu lệnh resume vào báo cáo. Khi chưa đủ prediction, báo progress là progress;
   chỉ điền accuracy trên 1.618 câu sau khi summary xác nhận hoàn tất. Tách accuracy
   trên gold không rỗng, token-cap failures, latency và tokens. Không tối ưu trên test
   sau khi xem điểm rồi vẫn gọi đó là đánh giá chưa từng thấy.

Mục tiêu cuối ngày mai: runner đã kiểm chứng và lượt đánh giá lớn đang chạy ổn định,
hoặc đã hoàn tất nếu thực tế nhanh hơn dự kiến. Không hứa có điểm cuối ngay trong ngày.

## Nhãn kết quả cần giữ

Đây là câu hỏi ViText2SQL ghép gold/database Spider gốc theo AST và literal, dùng schema
tiếng Anh. Là **adapted subset**, không phải full ViText2SQL nguyên bản hoặc điểm leaderboard
chính thức. Bản thích nghi chưa có independent human sample audit. Mốc 80% trên 20 câu
nghiệp vụ synthetic được giữ riêng, không suy rộng sang tập lớn.

Chi tiết protocol và lệnh: [VITEXT2SQL_LOCAL_EVAL.vi.md](VITEXT2SQL_LOCAL_EVAL.vi.md).
