"""Reference calculations over generated Python rows, without executing or parsing SQL.

Separate implementation is useful cross-checking, not independent human annotation.
Money is accumulated in integer cents to avoid large floating-point SUM drift.
"""

from __future__ import annotations

from datetime import datetime


def expected_values(rows: dict[str, list[dict]], region_id: int) -> dict[str, int | float]:
    customers = {c["customer_id"] for c in rows["customers"] if c["region_id"] == region_id}
    orders = {o["order_id"]: o for o in rows["orders"] if o["customer_id"] in customers}
    suppliers = {s["supplier_id"] for s in rows["suppliers"] if s["region_id"] == region_id}
    products = {p["product_id"]: p for p in rows["products"]}
    local_products = {p["product_id"] for p in rows["products"] if p["supplier_id"] in suppliers}
    h1_start, q2_start, h2_start = datetime(2026, 1, 1), datetime(2026, 4, 1), datetime(2026, 7, 1)
    year_end = datetime(2027, 1, 1)
    units = 0
    categories = set()
    for item in rows["order_items"]:
        order = orders.get(item["order_id"])
        if order is None or order["status"] == "cancelled":
            continue
        categories.add(products[item["product_id"]]["category_id"])
        if h1_start <= order["created_at"] < year_end:
            units += item["quantity"]
    payments = [
        p
        for p in rows["payments"]
        if p["order_id"] in orders
        and p["status"] == "succeeded"
        and p["paid_at"] is not None
        and q2_start <= p["paid_at"] < h2_start
    ]
    return {
        "active_customers": sum(
            c["customer_id"] in customers and c["status"] == "active" for c in rows["customers"]
        ),
        "cancelled_orders": sum(
            o["status"] == "cancelled" and h1_start <= o["created_at"] < h2_start
            for o in orders.values()
        ),
        "revenue_q2": sum(round(p["amount"] * 100) for p in payments) / 100,
        "units_2026": units,
        "low_stock": sum(
            i["product_id"] in local_products and i["quantity"] <= i["reorder_level"]
            for i in rows["inventory"]
        ),
        "active_products": sum(
            p["product_id"] in local_products and p["is_active"] for p in rows["products"]
        ),
        "delivered_shipments": sum(
            s["order_id"] in orders and s["status"] == "delivered" for s in rows["shipments"]
        ),
        "positive_reviews": sum(
            v["customer_id"] in customers and v["rating"] >= 4 for v in rows["reviews"]
        ),
        "default_addresses": sum(
            a["region_id"] == region_id and a["is_default"] for a in rows["addresses"]
        ),
        "sold_categories": len(categories),
    }
