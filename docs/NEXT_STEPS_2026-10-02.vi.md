# Kế hoạch ngày 02/10/2026

Task được tạm dừng theo yêu cầu người dùng ngày 01/10. Không có tiến trình live eval
của repo đang chạy; chưa khởi động lượt model trên adapted test split.

## Trạng thái đã có

- Đã tích hợp downloader có version/hash, preflight nhiều database và runner checkpoint.
- Package dev-v3: 898 câu hợp lệ / 25 database, từ 954 câu nguồn.
- Package test-v2: 1.618 câu hợp lệ / 42 database, từ 1.908 câu nguồn;
  1.004 cặp database–SQL AST khác nhau. Danh sách 290 câu loại trừ đã lưu riêng.
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
   cap 4096, cùng protocol đã chốt. Chạy agent trước để lấy metric cho CV; baseline
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
