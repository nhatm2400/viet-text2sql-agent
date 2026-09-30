"""AI-authored Python cross-checks for all 30 test golds; not human annotation.

Consume table rows, not gold SQL. Decimal aggregates avoid binary SUM drift.
"""

from collections import Counter, defaultdict
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal


def rounded(value):
    return float(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def total(rows, column):
    return sum((Decimal(str(r[column])) for r in rows), Decimal(0))


def groups(rows, key):
    result = defaultdict(list)
    for row in rows:
        result[key(row)].append(row)
    return result


def references(data):
    customers = {r["customer_id"]: r for r in data["customers"]}
    orders = {r["order_id"]: r for r in data["orders"]}
    products = {r["product_id"]: r for r in data["products"]}
    categories = {r["category_id"]: r for r in data["categories"]}
    succeeded = [r for r in data["payments"] if r["status"] == "succeeded"]
    paid_orders = {r["order_id"] for r in succeeded}
    q2 = lambda value: value is not None and "2026-04-01" <= value < "2026-07-01"  # noqa: E731
    h1 = lambda value: "2026-01-01" <= value < "2026-07-01"  # noqa: E731
    year = lambda value: "2026-01-01" <= value < "2027-01-01"  # noqa: E731
    result = {}
    revenue = groups(
        [r for r in succeeded if q2(r["paid_at"])],
        lambda r: (r["method"], customers[orders[r["order_id"]]["customer_id"]]["segment"]),
    )
    result[1] = [(*key, rounded(total(rows, "amount"))) for key, rows in sorted(revenue.items())]
    methods = defaultdict(set)
    for row in succeeded:
        methods[orders[row["order_id"]]["customer_id"]].add(row["method"])
    result[2] = [(sum(len(values) >= 2 for values in methods.values()),)]
    channels = groups([r for r in orders.values() if h1(r["created_at"])], lambda r: r["channel"])
    result[3] = [
        (
            key,
            len(rows),
            rounded(Decimal(100) * sum(r["status"] == "cancelled" for r in rows) / len(rows)),
        )
        for key, rows in sorted(channels.items())
    ]
    channels = groups(
        [r for r in orders.values() if q2(r["created_at"]) and r["order_id"] in paid_orders],
        lambda r: r["channel"],
    )
    result[4] = [
        (key, rounded(total(rows, "total_amount") / len(rows)))
        for key, rows in sorted(channels.items())
    ]
    buyers = {r["customer_id"] for r in orders.values()}
    result[5] = [(len(set(customers) - buyers),)]
    repeat = Counter(
        r["customer_id"]
        for r in orders.values()
        if r["status"] == "completed" and h1(r["created_at"])
    )
    result[6] = [(sum(n >= 3 for n in repeat.values()),)]
    quantities = Counter()
    for row in data["order_items"]:
        order = orders[row["order_id"]]
        if order["status"] == "completed" and year(order["created_at"]):
            quantities[products[row["product_id"]]["category_id"]] += row["quantity"]
    result[7] = [
        (key, categories[key]["category_name"], n)
        for key, n in sorted(quantities.items(), key=lambda pair: (-pair[1], pair[0]))[:5]
    ]
    sold = {r["product_id"] for r in data["order_items"]}
    result[8] = [(len(set(products) - sold),)]
    warehouses = groups(data["inventory"], lambda r: r["warehouse"])
    result[9] = [
        (key, sum(r["quantity"] for r in rows), len({r["product_id"] for r in rows}))
        for key, rows in sorted(warehouses.items())
    ]
    inventory = groups(data["inventory"], lambda r: r["product_id"])
    # Existing inventory records only: ambiguity in original wording is reported separately.
    result[10] = [
        (key,) for key, rows in sorted(inventory.items()) if sum(r["quantity"] for r in rows) == 0
    ]
    active_catalog = Counter(r["supplier_id"] for r in products.values() if r["is_active"])
    result[11] = [
        (r["supplier_id"], active_catalog[r["supplier_id"]])
        for r in sorted(data["suppliers"], key=lambda r: r["supplier_id"])
        if r["is_active"]
    ]
    reviews = groups(data["reviews"], lambda r: r["product_id"])
    ranks = [
        (key, len(rows), rounded(total(rows, "rating") / len(rows)))
        for key, rows in reviews.items()
        if len(rows) >= 10
    ]
    result[12] = sorted(ranks, key=lambda row: (-row[2], row[0]))[:5]
    result[13] = [(sum(r["is_active"] and key not in reviews for key, r in products.items()),)]
    payment_groups = groups(succeeded, lambda r: r["method"])
    result[14] = [
        (key, len(rows), rounded(total(rows, "amount")))
        for key, rows in sorted(payment_groups.items())
    ]
    result[15] = [
        (sum(r["status"] != "cancelled" and key not in paid_orders for key, r in orders.items()),)
    ]
    refunded = [r for r in data["payments"] if r["status"] == "refunded"]
    result[16] = [(rounded(total(refunded, "amount")) if refunded else None,)]
    carriers = Counter(r["carrier"] for r in data["shipments"] if r["status"] == "delivered")
    result[17] = sorted(carriers.items(), key=lambda pair: (-pair[1], pair[0]))
    delayed = 0
    for row in data["shipments"]:
        if row["status"] == "delivered" and row["delivered_at"] and row["shipped_at"]:
            seconds = (
                datetime.fromisoformat(row["delivered_at"])
                - datetime.fromisoformat(row["shipped_at"])
            ).total_seconds()
            delayed += seconds > 5 * 86400
    result[18] = [(delayed,)]
    addresses = Counter(r["customer_id"] for r in data["addresses"])
    result[19] = [(sum(n > 1 for n in addresses.values()),)]
    result[20] = [(len({r["customer_id"] for r in data["addresses"] if r["city"] == "TP.HCM"}),)]
    segments = Counter(
        r["segment"] for r in customers.values() if "2026-01-01" <= r["created_at"] < "2026-04-01"
    )
    result[21] = sorted(segments.items())
    completed = [r for r in orders.values() if r["status"] == "completed"]
    denominator = total(completed, "total_amount") + total(completed, "discount")
    result[22] = [
        (rounded(100 * total(completed, "discount") / denominator) if denominator else None,)
    ]
    result[23] = [
        (r["order_id"], r["total_amount"])
        for r in sorted(completed, key=lambda r: (-r["total_amount"], r["order_id"]))[:10]
    ]
    avg_price = total(products.values(), "unit_price") / len(products) if products else None
    result[24] = [
        (
            sum(Decimal(str(r["unit_price"])) > avg_price for r in products.values())
            if products
            else 0,
        )
    ]
    result[25] = [
        (key, r["category_name"], categories[r["parent_category_id"]]["category_name"])
        for key, r in sorted(categories.items())
        if r["parent_category_id"] is not None
    ]
    channel_buyers = defaultdict(set)
    customer_channels = defaultdict(set)
    for row in completed:
        customer_channels[row["customer_id"]].add(row["channel"])
        if h1(row["created_at"]):
            channel_buyers[row["channel"]].add(row["customer_id"])
    result[26] = [(key, len(values)) for key, values in sorted(channel_buyers.items())]
    result[27] = [(sum({"web", "app"} <= values for values in customer_channels.values()),)]
    result[28] = [(sum(len({r["warehouse"] for r in rows}) >= 3 for rows in inventory.values()),)]
    distribution = Counter(
        (customers[r["customer_id"]]["segment"], r["status"]) for r in orders.values()
    )
    result[29] = [(*key, n) for key, n in sorted(distribution.items())]
    result[30] = [
        (
            sum(
                q2(r["paid_at"]) and orders[r["order_id"]]["created_at"] < "2026-04-01"
                for r in succeeded
            ),
        )
    ]
    return {f"test_{key:02d}": rows for key, rows in result.items()}
