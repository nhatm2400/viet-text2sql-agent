"""Deterministic synthetic data for the 12-table e-commerce schema.

Run:
    make seed                      # uses DATABASE_URL from the environment
    python db/seed.py --url sqlite:///data/dev.sqlite

Determinism is the point: every reported evaluation number is tied to a database snapshot,
and the snapshot must be reproducible from this file alone. The RNG seed is fixed and the
"now" anchor is a constant, never `datetime.now()` — otherwise gold SQL with date literals
would silently drift out of range.

Accepts any SQLAlchemy URL. Postgres is the deployment target; SQLite is what the author
uses to execute and verify `gold_sql` for every eval item before it is committed (see
eval/datasets/core_vi/questions.jsonl).
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, text

# --- determinism knobs -------------------------------------------------------
RNG_SEED = 20260727
# Anchor for all generated timestamps. Data spans SNAPSHOT_START .. SNAPSHOT_END inclusive.
SNAPSHOT_START = datetime(2025, 1, 1)
SNAPSHOT_END = datetime(2026, 6, 30, 23, 59)

N_CUSTOMERS = 5_000
N_PRODUCTS = 300
N_SUPPLIERS = 40
N_ORDERS = 20_000  # -> ~45k order_items, comfortably under the 50k row budget

SCHEMA_SQL = Path(__file__).with_name("schema.sql")

REGIONS = [
    (1, "Miền Bắc", "NORTH"),
    (2, "Miền Trung", "CENTRAL"),
    (3, "Miền Nam", "SOUTH"),
]

CITIES = {
    1: ["Hà Nội", "Hải Phòng", "Bắc Ninh", "Quảng Ninh"],
    2: ["Đà Nẵng", "Huế", "Nha Trang", "Quy Nhơn"],
    3: ["TP.HCM", "Cần Thơ", "Biên Hòa", "Vũng Tàu"],
}

SURNAMES = ["Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Huỳnh", "Phan", "Vũ", "Đặng", "Bùi"]
MIDDLE = ["Văn", "Thị", "Hữu", "Ngọc", "Minh", "Thanh", "Quốc", "Gia"]
GIVEN = [
    "An",
    "Bình",
    "Cường",
    "Dung",
    "Hà",
    "Khánh",
    "Linh",
    "Mai",
    "Nam",
    "Phúc",
    "Quân",
    "Trang",
]

CATEGORY_NAMES = [
    "Electronics",
    "Mobile Phones",
    "Laptops",
    "Home Appliances",
    "Kitchen",
    "Fashion",
    "Men Apparel",
    "Women Apparel",
    "Footwear",
    "Beauty",
    "Groceries",
    "Beverages",
    "Books",
    "Toys",
    "Sports",
    "Furniture",
    "Office Supplies",
    "Automotive",
    "Pet Supplies",
    "Garden",
]

PRODUCT_WORDS = ["Pro", "Max", "Lite", "Plus", "Mini", "Ultra", "Classic", "Prime", "Neo", "Air"]
WAREHOUSES = ["HN-01", "DN-01", "HCM-01", "HCM-02"]
CARRIERS = ["GHN", "GHTK", "ViettelPost", "J&T", "VNPost"]

TABLES_IN_LOAD_ORDER = [
    "reviews",
    "shipments",
    "payments",
    "order_items",
    "orders",
    "inventory",
    "products",
    "suppliers",
    "categories",
    "addresses",
    "customers",
    "regions",
]


def _rand_dt(
    rng: random.Random, start: datetime = SNAPSHOT_START, end: datetime = SNAPSHOT_END
) -> datetime:
    span = int((end - start).total_seconds())
    return start + timedelta(seconds=rng.randrange(span))


def _full_name(rng: random.Random) -> str:
    return f"{rng.choice(SURNAMES)} {rng.choice(MIDDLE)} {rng.choice(GIVEN)}"


def _split_statements(sql: str, dialect: str) -> list[str]:
    """Split schema.sql into statements for `dialect`.

    Uses sqlglot rather than splitting on ';' — the schema has trailing `--` comments that
    contain semicolons, and a naive split truncates the CREATE TABLE right through them.
    Transpiling also lets the same Postgres DDL create the throwaway SQLite database used to
    verify every `gold_sql` before it is committed.
    """
    import sqlglot

    return sqlglot.transpile(sql, read="postgres", write=dialect, pretty=False)


def build_rows() -> dict[str, list[dict]]:
    """Generate every table's rows in memory. Pure function of RNG_SEED."""
    rng = random.Random(RNG_SEED)
    rows: dict[str, list[dict]] = {}

    rows["regions"] = [
        {"region_id": rid, "region_name": name, "region_code": code} for rid, name, code in REGIONS
    ]

    rows["categories"] = [
        {
            "category_id": i + 1,
            "category_name": name,
            "parent_category_id": None if i < 5 else rng.randint(1, 5),
        }
        for i, name in enumerate(CATEGORY_NAMES)
    ]

    rows["suppliers"] = [
        {
            "supplier_id": i + 1,
            "supplier_name": f"Supplier {i + 1:03d}",
            "region_id": rng.randint(1, 3),
            "is_active": rng.random() > 0.1,
        }
        for i in range(N_SUPPLIERS)
    ]

    customers = []
    for cid in range(1, N_CUSTOMERS + 1):
        region_id = rng.choices([1, 2, 3], weights=[35, 20, 45])[0]
        customers.append(
            {
                "customer_id": cid,
                "full_name": _full_name(rng),
                "email": f"user{cid}@example.com",
                "phone": f"09{rng.randrange(10**8):08d}",
                "segment": rng.choices(["retail", "wholesale", "vip"], weights=[70, 20, 10])[0],
                "status": rng.choices(["active", "inactive", "churned"], weights=[75, 15, 10])[0],
                "region_id": region_id,
                "created_at": _rand_dt(rng, SNAPSHOT_START, datetime(2026, 3, 31)),
            }
        )
    rows["customers"] = customers

    addresses = []
    aid = 0
    for c in customers:
        for n in range(rng.choices([1, 2], weights=[80, 20])[0]):
            aid += 1
            addresses.append(
                {
                    "address_id": aid,
                    "customer_id": c["customer_id"],
                    "line1": f"{rng.randint(1, 300)} Đường số {rng.randint(1, 60)}",
                    "city": rng.choice(CITIES[c["region_id"]]),
                    "region_id": c["region_id"],
                    "is_default": n == 0,
                }
            )
    rows["addresses"] = addresses

    products = []
    for pid in range(1, N_PRODUCTS + 1):
        cat = rng.randint(1, len(CATEGORY_NAMES))
        products.append(
            {
                "product_id": pid,
                "product_name": f"{CATEGORY_NAMES[cat - 1].split()[0]} {rng.choice(PRODUCT_WORDS)} {pid}",
                "sku": f"SKU-{pid:05d}",
                "category_id": cat,
                "supplier_id": rng.randint(1, N_SUPPLIERS),
                "unit_price": round(rng.uniform(50_000, 25_000_000), 2),
                "is_active": rng.random() > 0.08,
                "created_at": _rand_dt(rng, SNAPSHOT_START, datetime(2025, 12, 31)),
            }
        )
    rows["products"] = products

    inventory = []
    inv_id = 0
    for p in products:
        for wh in rng.sample(WAREHOUSES, k=rng.randint(1, 3)):
            inv_id += 1
            inventory.append(
                {
                    "inventory_id": inv_id,
                    "product_id": p["product_id"],
                    "warehouse": wh,
                    "quantity": rng.randint(0, 500),
                    "reorder_level": rng.choice([10, 20, 50]),
                    "updated_at": _rand_dt(rng, datetime(2026, 5, 1)),
                }
            )
    rows["inventory"] = inventory

    orders, order_items, payments, shipments = [], [], [], []
    oi_id = pay_id = ship_id = 0
    for oid in range(1, N_ORDERS + 1):
        cust = customers[rng.randrange(N_CUSTOMERS)]
        created = _rand_dt(rng, max(SNAPSHOT_START, cust["created_at"]))
        status = rng.choices(
            ["completed", "shipped", "paid", "pending", "cancelled", "refunded"],
            weights=[55, 12, 12, 9, 8, 4],
        )[0]

        items = []
        for _ in range(rng.randint(1, 4)):
            p = products[rng.randrange(N_PRODUCTS)]
            qty = rng.randint(1, 5)
            unit = float(p["unit_price"])
            oi_id += 1
            items.append(
                {
                    "order_item_id": oi_id,
                    "order_id": oid,
                    "product_id": p["product_id"],
                    "quantity": qty,
                    "unit_price": round(unit, 2),
                    "line_total": round(unit * qty, 2),
                }
            )
        order_items.extend(items)

        subtotal = round(sum(i["line_total"] for i in items), 2)
        discount = round(subtotal * rng.choice([0, 0, 0, 0.05, 0.1]), 2)
        total = round(subtotal - discount, 2)
        completed_at = (
            created + timedelta(days=rng.randint(1, 10)) if status == "completed" else None
        )
        if completed_at and completed_at > SNAPSHOT_END:
            completed_at = SNAPSHOT_END

        orders.append(
            {
                "order_id": oid,
                "customer_id": cust["customer_id"],
                "status": status,
                "channel": rng.choices(
                    ["web", "app", "store", "marketplace"], weights=[40, 35, 15, 10]
                )[0],
                "total_amount": total,
                "discount": discount,
                "created_at": created,
                "completed_at": completed_at,
            }
        )

        # payments: money is only "revenue" when status='succeeded' AND paid_at is set.
        if status in ("paid", "shipped", "completed", "refunded"):
            pay_status = "refunded" if status == "refunded" else "succeeded"
            paid_at = created + timedelta(minutes=rng.randint(1, 2880))
            pay_id += 1
            payments.append(
                {
                    "payment_id": pay_id,
                    "order_id": oid,
                    "method": rng.choices(
                        ["cod", "card", "bank_transfer", "ewallet"], weights=[30, 25, 20, 25]
                    )[0],
                    "status": pay_status,
                    "amount": total,
                    "paid_at": min(paid_at, SNAPSHOT_END),
                }
            )
        elif rng.random() < 0.3:  # a failed attempt on some pending orders
            pay_id += 1
            payments.append(
                {
                    "payment_id": pay_id,
                    "order_id": oid,
                    "method": "card",
                    "status": rng.choice(["pending", "failed"]),
                    "amount": total,
                    "paid_at": None,
                }
            )

        if status in ("shipped", "completed"):
            ship_id += 1
            shipped_at = created + timedelta(days=rng.randint(1, 4))
            delivered = status == "completed"
            shipments.append(
                {
                    "shipment_id": ship_id,
                    "order_id": oid,
                    "carrier": rng.choice(CARRIERS),
                    "status": "delivered" if delivered else "in_transit",
                    "shipped_at": min(shipped_at, SNAPSHOT_END),
                    "delivered_at": completed_at if delivered else None,
                    "address_id": rng.randint(1, len(addresses)),
                }
            )

    rows["orders"] = orders
    rows["order_items"] = order_items
    rows["payments"] = payments
    rows["shipments"] = shipments

    reviews = []
    for rid, item in enumerate(rng.sample(order_items, k=len(order_items) // 6), start=1):
        order = orders[item["order_id"] - 1]
        reviews.append(
            {
                "review_id": rid,
                "product_id": item["product_id"],
                "customer_id": order["customer_id"],
                "rating": rng.choices([1, 2, 3, 4, 5], weights=[5, 8, 17, 35, 35])[0],
                "comment": rng.choice(
                    ["Giao nhanh", "Hàng tốt", "Tạm ổn", "Không như mô tả", None]
                ),
                "created_at": order["created_at"] + timedelta(days=rng.randint(2, 30)),
            }
        )
    rows["reviews"] = reviews

    return rows


def seed(url: str, *, drop: bool = True) -> dict[str, int]:
    engine = create_engine(url)
    dialect = "sqlite" if engine.dialect.name == "sqlite" else "postgres"
    rows = build_rows()
    counts = {t: len(rows[t]) for t in rows}

    with engine.begin() as conn:
        if drop:
            for table in TABLES_IN_LOAD_ORDER:
                conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
        for stmt in _split_statements(SCHEMA_SQL.read_text(encoding="utf-8"), dialect):
            conn.execute(text(stmt))

        for table in reversed(TABLES_IN_LOAD_ORDER):
            data = rows[table]
            if not data:
                continue
            cols = list(data[0].keys())
            insert = text(
                f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(':' + c for c in cols)})"
            )
            for start in range(0, len(data), 2_000):
                conn.execute(insert, data[start : start + 2_000])

    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Seed the e-commerce schema with deterministic data."
    )
    parser.add_argument("--url", default=os.getenv("DATABASE_URL", ""), help="SQLAlchemy URL")
    parser.add_argument("--keep", action="store_true", help="do not DROP existing tables first")
    args = parser.parse_args(argv)

    if not args.url:
        print(
            "DATABASE_URL is not set — nothing to seed.\n"
            "  Postgres : export DATABASE_URL=postgresql+psycopg://user:pw@localhost:5432/t2sql\n"
            "             (local dev: ssh -L 5432:localhost:5432 user@vps first)\n"
            "  SQLite   : python db/seed.py --url sqlite:///data/dev.sqlite"
        )
        return 0

    if args.url.startswith("sqlite"):
        Path("data").mkdir(exist_ok=True)

    counts = seed(args.url, drop=not args.keep)
    print(
        f"Seeded (RNG_SEED={RNG_SEED}, snapshot {SNAPSHOT_START:%Y-%m-%d}..{SNAPSHOT_END:%Y-%m-%d}):"
    )
    for table in reversed(TABLES_IN_LOAD_ORDER):
        print(f"  {table:<12} {counts[table]:>7,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
