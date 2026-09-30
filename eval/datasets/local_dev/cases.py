"""AI-authored development cases, pending independent human review.

Ten query families expanded over three regions: 30 cases, NOT 30 independent intents.
No held-out test claim. All dates and business definitions are explicit in the questions.
Gold SQL and deliberately wrong SQL are authored here; Python oracles live separately.
"""

from __future__ import annotations

REGIONS = [(1, "NORTH", "miền Bắc"), (2, "CENTRAL", "miền Trung"), (3, "SOUTH", "miền Nam")]

CUSTOMER_REGION = (
    "JOIN customers c ON c.customer_id = o.customer_id JOIN regions r ON r.region_id = c.region_id "
)
SUPPLIER_REGION = (
    "JOIN suppliers s ON s.supplier_id = pr.supplier_id "
    "JOIN regions r ON r.region_id = s.region_id "
)

# family, Vietnamese question, English question, SQL, mutation-from, mutation-to, failure type
FAMILIES = [
    (
        "active_customers",
        "Có bao nhiêu khách hàng ở {region} có customers.status = 'active'?",
        "How many customers in {code} have customers.status = 'active'?",
        "SELECT COUNT(*) AS value FROM customers c JOIN regions r ON r.region_id = c.region_id "
        "WHERE r.region_code = '{code}' AND c.status = 'active'",
        "c.status = 'active'",
        "c.status = 'inactive'",
        "wrong_status",
    ),
    (
        "cancelled_orders",
        "Đếm đơn bị hủy của khách ở {region}, đặt từ 01/01 đến trước 01/07/2026.",
        "Count cancelled orders placed in H1 2026 by customers in {code}.",
        "SELECT COUNT(*) AS value FROM orders o "
        + CUSTOMER_REGION
        + "WHERE r.region_code = '{code}' AND o.status = 'cancelled' "
        "AND o.created_at >= '2026-01-01' AND o.created_at < '2026-07-01'",
        "o.status = 'cancelled'",
        "o.status = 'completed'",
        "wrong_status",
    ),
    (
        "revenue_q2",
        "Tổng payments.amount đã succeeded trong quý 2/2026 theo paid_at, của khách ở {region}; làm tròn 2 chữ số.",
        "Sum succeeded payments.amount in Q2 2026 by paid_at for customers in {code}; round to 2 decimals.",
        "SELECT ROUND(SUM(p.amount), 2) AS value FROM payments p "
        "JOIN orders o ON o.order_id = p.order_id "
        + CUSTOMER_REGION
        + "WHERE r.region_code = '{code}' AND p.status = 'succeeded' "
        "AND p.paid_at >= '2026-04-01' AND p.paid_at < '2026-07-01'",
        "p.paid_at",
        "o.created_at",
        "wrong_time_anchor",
    ),
    (
        "units_2026",
        "Tổng số lượng order_items của đơn đặt năm 2026, loại đơn cancelled, của khách ở {region}?",
        "Total item quantity in orders placed in 2026, excluding cancelled, for customers in {code}?",
        "SELECT SUM(oi.quantity) AS value FROM order_items oi "
        "JOIN orders o ON o.order_id = oi.order_id "
        + CUSTOMER_REGION
        + "WHERE r.region_code = '{code}' AND o.status <> 'cancelled' "
        "AND o.created_at >= '2026-01-01' AND o.created_at < '2027-01-01'",
        "SUM(oi.quantity)",
        "COUNT(*)",
        "count_instead_of_quantity",
    ),
    (
        "low_stock",
        "Đếm dòng tồn kho có quantity <= reorder_level, sản phẩm thuộc nhà cung cấp ở {region}.",
        "Count inventory rows with quantity <= reorder_level for products supplied from {code}.",
        "SELECT COUNT(*) AS value FROM inventory i "
        "JOIN products pr ON pr.product_id = i.product_id "
        + SUPPLIER_REGION
        + "WHERE r.region_code = '{code}' AND i.quantity <= i.reorder_level",
        "i.quantity <= i.reorder_level",
        "i.quantity >= i.reorder_level",
        "reversed_threshold",
    ),
    (
        "active_products",
        "Đếm sản phẩm có is_active = TRUE của nhà cung cấp ở {region}, không lọc trạng thái nhà cung cấp.",
        "Count active products from suppliers in {code}, regardless of supplier active status.",
        "SELECT COUNT(*) AS value FROM products pr "
        + SUPPLIER_REGION
        + "WHERE r.region_code = '{code}' AND pr.is_active = TRUE",
        "pr.is_active = TRUE",
        "pr.is_active = FALSE",
        "wrong_boolean",
    ),
    (
        "delivered_shipments",
        "Đếm shipment có status = 'delivered' của khách ở {region}, xác định miền qua khách hàng của đơn.",
        "Count delivered shipments for customers in {code}, locating region through the order customer.",
        "SELECT COUNT(*) AS value FROM shipments sh JOIN orders o ON o.order_id = sh.order_id "
        + CUSTOMER_REGION
        + "WHERE r.region_code = '{code}' AND sh.status = 'delivered'",
        "sh.status = 'delivered'",
        "sh.status = 'in_transit'",
        "wrong_status",
    ),
    (
        "positive_reviews",
        "Đếm review từ 4 sao trở lên của khách ở {region}, trên toàn bộ dữ liệu.",
        "Count reviews rated at least 4 by customers in {code}, across all data.",
        "SELECT COUNT(*) AS value FROM reviews v JOIN customers c ON c.customer_id = v.customer_id "
        "JOIN regions r ON r.region_id = c.region_id "
        "WHERE r.region_code = '{code}' AND v.rating >= 4",
        "v.rating >= 4",
        "v.rating >= 5",
        "wrong_threshold",
    ),
    (
        "default_addresses",
        "Đếm địa chỉ mặc định có addresses.region_id thuộc {region}.",
        "Count default addresses whose addresses.region_id is in {code}.",
        "SELECT COUNT(*) AS value FROM addresses a JOIN regions r ON r.region_id = a.region_id "
        "WHERE r.region_code = '{code}' AND a.is_default = TRUE",
        "a.is_default = TRUE",
        "a.is_default = FALSE",
        "wrong_boolean",
    ),
    (
        "sold_categories",
        "Có bao nhiêu category_id khác nhau xuất hiện trong đơn không cancelled của khách ở {region}, toàn kỳ?",
        "How many distinct category IDs occur in non-cancelled orders by customers in {code}, all time?",
        "SELECT COUNT(DISTINCT cat.category_id) AS value FROM categories cat "
        "JOIN products pr ON pr.category_id = cat.category_id "
        "JOIN order_items oi ON oi.product_id = pr.product_id "
        "JOIN orders o ON o.order_id = oi.order_id "
        + CUSTOMER_REGION
        + "WHERE r.region_code = '{code}' AND o.status <> 'cancelled'",
        "COUNT(DISTINCT cat.category_id)",
        "COUNT(cat.category_id)",
        "missing_distinct",
    ),
]


def build_cases() -> list[dict]:
    cases = []
    for family, vi, en, template, old, new, error in FAMILIES:
        for region_id, code, region in REGIONS:
            sql = template.format(code=code)
            cases.append(
                {
                    "id": f"{family}_{code.lower()}",
                    "family": family,
                    "region_id": region_id,
                    "question_vi": vi.format(region=region),
                    "question_en": en.format(code=code),
                    "gold_sql": sql,
                    "mutant_sql": sql.replace(old, new),
                    "mutation": error,
                    "split": "development",
                    "authoring": "AI-assisted; no external dataset",
                    "human_review": "pending",
                    "version": "local-dev-v1",
                }
            )
    return cases
