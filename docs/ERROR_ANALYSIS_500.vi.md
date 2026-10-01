# Phân tích 195 câu sai strict — 02/10/2026

Đã replay gold/prediction trên database đã pin và kiểm tra hashes của run 500.
Không gọi model, không sửa prediction hoặc scorer. [Aggregate có hashes](evidence/vitext2sql-prefix-500-error-analysis-20261002.json).

| Nhóm quan sát, không chồng lấp | Số câu |
|---|---:|
| Khớp relaxed, khác projection/thứ tự cột so với strict | 58 |
| SQL chạy thành công, khác số dòng | 61 |
| Không có SQL chạy thành công, có model call chạm output cap | 36 |
| SQL chạy thành công, thiếu cột so với gold | 7 |
| Khớp khi bỏ yêu cầu thứ tự dòng | 1 |
| Cùng số dòng, đủ cột, vẫn khác giá trị/projection | 32 |
| Tổng strict misses | **195** |

305 câu strict đúng còn lại tạo thành đủ 500 predictions. Trong 195 misses, 39 câu
có ít nhất một model call chạm cap; 36 thuộc nhóm không có SQL thành công, 3 đã chạy
SQL nhưng vẫn sai. Toàn bộ 500 có 40 câu chạm cap: một câu vẫn strict đúng. Vì vậy,
không coi mọi lần chạm cap là một prediction sai hoặc cộng các nhóm chồng lấp.

Các tín hiệu AST phụ được lưu riêng: khác tables 126, filters 80, joins 75, grouping 67,
literals 63, aggregates 60, ordering 29, set operations 17, having 4, limits 1. Tín hiệu
có thể chồng lấp; alias, cách viết tương đương và các phép biến đổi SQL cũng tạo AST
khác nhau. Đây không phải bằng chứng rằng 126 câu sai do schema linking hay 80 câu sai
do filter. Chưa có independent human semantic review.

## Việc nên thử tiếp

1. Kiểm tra một tập development riêng cho 36 trường hợp không xuất SQL: đo ảnh hưởng
   của thinking/output budget/context tới tỷ lệ tạo SQL, accuracy và latency. Không chỉ
   tăng budget rồi kết luận sẽ sửa hết 36 câu.
2. Thêm hướng dẫn và example retrieval trên development cho đúng projection theo yêu
   cầu. 58 relaxed hits là vùng cần kiểm tra, không tự cộng vào strict accuracy.
3. Review các nhóm khác số dòng và giá trị, tập trung join/filter/grouping/aggregation.
   Chỉ gán root cause khi đối chiếu câu hỏi, gold và SQL; giữ trạng thái AI-assisted nếu
   chưa có người độc lập duyệt.
4. Đóng băng thay đổi rồi chạy một tập test mới giữ riêng. Không tối ưu dựa vào 500 câu
   đã xem và gọi kết quả mới là test chưa từng thấy.

Chi tiết từng câu, gồm dữ liệu có giấy phép hạn chế, chỉ nằm trong thư mục bị Git ignore:
`eval/results/20261001-030508-057723-vitext2sql-test/analysis/prefix-500-failures.json`.

## Tái chạy, không gọi model

```powershell
.venv/Scripts/python.exe -m eval.harness.analyze_vitext2sql --run eval/results/20261001-030508-057723-vitext2sql-test --prefix-size 500 --output eval/results/error-analysis-500-new.json
```

Output tổng hợp phải là file mới; chi tiết cục bộ được ghi lại dưới thư mục analysis.
Metric lịch sử vẫn là **61,0% strict / 72,6% relaxed**.
