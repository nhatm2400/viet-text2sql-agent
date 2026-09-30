"""Review candidates, never automatically promoted to a human-reviewed test set.

20 development questions reuse 10 established families; 30 test candidates are separately
authored. A reviewer must confirm semantics, diversity and split before freezing the manifest.
"""

from eval.datasets.local_dev.cases import build_cases

# Explicit business rules and fixed dates avoid using the unimplemented time resolver.
TEST_CANDIDATES = [
    (
        "revenue_method_segment",
        "Tiền thanh toán succeeded quý 2/2026 theo paid_at, chia theo method và segment khách? Trả method, segment và tổng amount làm tròn 2 số; xếp method rồi segment.",
        "SELECT p.method,c.segment,ROUND(SUM(p.amount),2) AS revenue FROM payments p JOIN orders o ON o.order_id=p.order_id JOIN customers c ON c.customer_id=o.customer_id WHERE p.status='succeeded' AND p.paid_at >= '2026-04-01' AND p.paid_at < '2026-07-01' GROUP BY p.method,c.segment ORDER BY p.method,c.segment",
    ),
    (
        "multiple_payment_methods",
        "Có bao nhiêu khách đã thanh toán succeeded bằng ít nhất 2 method khác nhau, trên toàn bộ dữ liệu?",
        "SELECT COUNT(*) AS n FROM (SELECT o.customer_id FROM orders o JOIN payments p ON p.order_id=o.order_id WHERE p.status='succeeded' GROUP BY o.customer_id HAVING COUNT(DISTINCT p.method)>=2) t",
    ),
    (
        "cancel_rate",
        "Tỷ lệ đơn cancelled theo kênh trong H1/2026 theo ngày đặt? Trả kênh, tổng đơn, phần trăm hủy làm tròn 2 số; xếp theo kênh.",
        "SELECT channel,COUNT(*) AS total_orders,ROUND(100.0*SUM(CASE WHEN status='cancelled' THEN 1 ELSE 0 END)/COUNT(*),2) AS cancelled_pct FROM orders WHERE created_at >= '2026-01-01' AND created_at < '2026-07-01' GROUP BY channel ORDER BY channel",
    ),
    (
        "aov_paid",
        "Giá trị đơn trung bình theo kênh trong quý 2/2026 theo ngày đặt, chỉ đơn có ít nhất một payment succeeded? Dùng orders.total_amount, làm tròn 2 số và xếp theo kênh.",
        "SELECT o.channel,ROUND(AVG(o.total_amount),2) AS aov FROM orders o WHERE o.created_at >= '2026-04-01' AND o.created_at < '2026-07-01' AND EXISTS (SELECT 1 FROM payments p WHERE p.order_id=o.order_id AND p.status='succeeded') GROUP BY o.channel ORDER BY o.channel",
    ),
    (
        "no_orders",
        "Có bao nhiêu khách chưa từng có đơn hàng?",
        "SELECT COUNT(*) AS n FROM customers c WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id=c.customer_id)",
    ),
    (
        "repeat_buyers",
        "Có bao nhiêu khách có ít nhất 3 đơn completed trong H1/2026 theo created_at?",
        "SELECT COUNT(*) AS n FROM (SELECT customer_id FROM orders WHERE status='completed' AND created_at >= '2026-01-01' AND created_at < '2026-07-01' GROUP BY customer_id HAVING COUNT(*)>=3) t",
    ),
    (
        "category_quantity",
        "Top 5 nhóm hàng theo tổng số lượng trong đơn completed năm 2026 theo created_at, trả category_id, tên, số lượng; hòa thì mã nhỏ trước.",
        "SELECT cat.category_id,cat.category_name,SUM(i.quantity) AS units FROM categories cat JOIN products pr ON pr.category_id=cat.category_id JOIN order_items i ON i.product_id=pr.product_id JOIN orders o ON o.order_id=i.order_id WHERE o.status='completed' AND o.created_at >= '2026-01-01' AND o.created_at < '2027-01-01' GROUP BY cat.category_id,cat.category_name ORDER BY units DESC,cat.category_id LIMIT 5",
    ),
    (
        "never_sold",
        "Có bao nhiêu sản phẩm chưa xuất hiện trong bất kỳ order_items nào?",
        "SELECT COUNT(*) AS n FROM products p WHERE NOT EXISTS (SELECT 1 FROM order_items i WHERE i.product_id=p.product_id)",
    ),
    (
        "inventory_by_warehouse",
        "Tổng tồn kho và số sản phẩm khác nhau theo warehouse? Xếp theo warehouse.",
        "SELECT warehouse,SUM(quantity) AS units,COUNT(DISTINCT product_id) AS products FROM inventory GROUP BY warehouse ORDER BY warehouse",
    ),
    (
        "out_of_stock",
        "Liệt kê mã sản phẩm có tổng tồn kho ở mọi kho bằng 0, sắp theo mã.",
        "SELECT product_id FROM inventory GROUP BY product_id HAVING SUM(quantity)=0 ORDER BY product_id",
    ),
    (
        "supplier_catalog",
        "Mỗi nhà cung cấp active có bao nhiêu sản phẩm active? Trả supplier_id và số lượng, giữ cả nhà cung cấp có 0 sản phẩm; xếp theo mã.",
        "SELECT s.supplier_id,COUNT(p.product_id) AS n FROM suppliers s LEFT JOIN products p ON p.supplier_id=s.supplier_id AND p.is_active=TRUE WHERE s.is_active=TRUE GROUP BY s.supplier_id ORDER BY s.supplier_id",
    ),
    (
        "review_rank",
        "Top 5 sản phẩm có ít nhất 10 review theo điểm trung bình; trả mã, số review và điểm làm tròn 2 số, xếp điểm đã làm tròn giảm dần rồi mã.",
        "SELECT product_id,COUNT(*) AS n,ROUND(AVG(rating),2) AS rating FROM reviews GROUP BY product_id HAVING COUNT(*)>=10 ORDER BY rating DESC,product_id LIMIT 5",
    ),
    (
        "unreviewed",
        "Có bao nhiêu sản phẩm active chưa có review?",
        "SELECT COUNT(*) AS n FROM products p WHERE p.is_active=TRUE AND NOT EXISTS (SELECT 1 FROM reviews r WHERE r.product_id=p.product_id)",
    ),
    (
        "payment_methods",
        "Theo từng method, có bao nhiêu payment succeeded và tổng amount bao nhiêu (2 số thập phân), toàn kỳ? Xếp theo method.",
        "SELECT method,COUNT(*) AS n,ROUND(SUM(amount),2) AS amount FROM payments WHERE status='succeeded' GROUP BY method ORDER BY method",
    ),
    (
        "unpaid_orders",
        "Có bao nhiêu đơn không cancelled và không có payment succeeded?",
        "SELECT COUNT(*) AS n FROM orders o WHERE o.status<>'cancelled' AND NOT EXISTS (SELECT 1 FROM payments p WHERE p.order_id=o.order_id AND p.status='succeeded')",
    ),
    (
        "refund_amount",
        "Tổng amount của payment có status refunded trong dữ liệu, làm tròn 2 số thập phân?",
        "SELECT ROUND(SUM(amount),2) AS amount FROM payments WHERE status='refunded'",
    ),
    (
        "delivery_carriers",
        "Số shipment delivered theo carrier, xếp số lượng giảm dần rồi tên carrier.",
        "SELECT carrier,COUNT(*) AS n FROM shipments WHERE status='delivered' GROUP BY carrier ORDER BY n DESC,carrier",
    ),
    (
        "delivery_delay",
        "Có bao nhiêu shipment delivered hơn 5 ngày sau shipped_at? So thời điểm chính xác, không đếm ngày lịch.",
        "SELECT COUNT(*) AS n FROM shipments WHERE status='delivered' AND julianday(delivered_at) - julianday(shipped_at) > 5",
    ),
    (
        "multiple_addresses",
        "Có bao nhiêu khách có hơn một địa chỉ?",
        "SELECT COUNT(*) AS n FROM (SELECT customer_id FROM addresses GROUP BY customer_id HAVING COUNT(*)>1) t",
    ),
    (
        "city_customers",
        "Số khách khác nhau có ít nhất một địa chỉ ở TP.HCM?",
        "SELECT COUNT(DISTINCT customer_id) AS n FROM addresses WHERE city='TP.HCM'",
    ),
    (
        "new_customers",
        "Đếm khách mới theo segment, created_at trong quý 1/2026; xếp theo segment.",
        "SELECT segment,COUNT(*) AS n FROM customers WHERE created_at >= '2026-01-01' AND created_at < '2026-04-01' GROUP BY segment ORDER BY segment",
    ),
    (
        "discount_ratio",
        "Tổng discount của đơn completed chia tổng giá trị trước discount (total_amount + discount), tính phần trăm 2 số, toàn kỳ?",
        "SELECT ROUND(100.0*SUM(discount)/SUM(total_amount+discount),2) AS pct FROM orders WHERE status='completed'",
    ),
    (
        "high_value_orders",
        "10 đơn completed có total_amount lớn nhất: trả order_id và total_amount, hòa thì mã nhỏ trước.",
        "SELECT order_id,total_amount FROM orders WHERE status='completed' ORDER BY total_amount DESC,order_id LIMIT 10",
    ),
    (
        "above_average_products",
        "Số sản phẩm có unit_price lớn hơn giá trung bình toàn bộ sản phẩm?",
        "SELECT COUNT(*) AS n FROM products WHERE unit_price > (SELECT AVG(unit_price) FROM products)",
    ),
    (
        "category_hierarchy",
        "Liệt kê category_id, tên nhóm con, tên nhóm cha của các nhóm có cha, xếp mã nhóm con.",
        "SELECT c.category_id,c.category_name AS child_name,p.category_name AS parent_name FROM categories c JOIN categories p ON p.category_id=c.parent_category_id ORDER BY c.category_id",
    ),
    (
        "distinct_buyers",
        "Số khách khác nhau có đơn completed theo kênh trong H1/2026 theo created_at, xếp kênh.",
        "SELECT channel,COUNT(DISTINCT customer_id) AS n FROM orders WHERE status='completed' AND created_at >= '2026-01-01' AND created_at < '2026-07-01' GROUP BY channel ORDER BY channel",
    ),
    (
        "both_channels",
        "Số khách đã có đơn completed ở cả web lẫn app, toàn kỳ?",
        "SELECT COUNT(*) AS n FROM (SELECT customer_id FROM orders WHERE status='completed' AND channel IN ('web','app') GROUP BY customer_id HAVING COUNT(DISTINCT channel)=2) t",
    ),
    (
        "multi_warehouse",
        "Có bao nhiêu sản phẩm có tồn kho tại ít nhất 3 warehouse khác nhau? Không yêu cầu quantity dương.",
        "SELECT COUNT(*) AS n FROM (SELECT product_id FROM inventory GROUP BY product_id HAVING COUNT(DISTINCT warehouse)>=3) t",
    ),
    (
        "customer_order_distribution",
        "Số đơn theo segment khách và status đơn, toàn kỳ; trả segment,status,n, xếp segment rồi status.",
        "SELECT c.segment,o.status,COUNT(*) AS n FROM customers c JOIN orders o ON o.customer_id=c.customer_id GROUP BY c.segment,o.status ORDER BY c.segment,o.status",
    ),
    (
        "payment_order_gap",
        "Trong payment succeeded quý 2/2026 theo paid_at, bao nhiêu payment thuộc đơn đặt trước quý 2?",
        "SELECT COUNT(*) AS n FROM payments p JOIN orders o ON o.order_id=p.order_id WHERE p.status='succeeded' AND p.paid_at >= '2026-04-01' AND p.paid_at < '2026-07-01' AND o.created_at < '2026-04-01'",
    ),
]


def candidates() -> list[dict]:
    dev = [dict(c, split="dev") for c in build_cases() if c["region_id"] != 3]
    test = [
        {
            "id": f"test_{i:02d}",
            "family": family,
            "question_vi": question,
            "gold_sql": sql,
            "split": "test",
            "authoring": "AI-assisted",
            "human_review": "pending",
        }
        for i, (family, question, sql) in enumerate(TEST_CANDIDATES, 1)
    ]
    return dev + test
