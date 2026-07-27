-- viet-text2sql-agent — 12-table English e-commerce schema.
--
-- Design notes (deliberate, for benchmark realism):
--   * All identifiers are English; the questions asked against them are Vietnamese.
--   * Timestamps are deliberately confusable: orders.created_at vs orders.completed_at vs
--     payments.paid_at. "doanh thu tháng 6" is ambiguous until the glossary pins it down —
--     this is the single most common source of silent SQL errors in this domain.
--   * Statuses are CHECK-constrained text rather than Postgres ENUM types so that the same
--     DDL can be parsed by sqlglot for the schema tools and mirrored into SQLite for tests.
--   * customers.email / customers.phone exist on purpose: they are the sensitive columns the
--     AST policy must refuse to return (see src/t2sql/guardrails/policy.yaml).

-- 1. regions -----------------------------------------------------------------
CREATE TABLE regions (
    region_id    INTEGER PRIMARY KEY,
    region_name  TEXT NOT NULL,          -- 'Miền Bắc' | 'Miền Trung' | 'Miền Nam'
    region_code  TEXT NOT NULL UNIQUE    -- 'NORTH' | 'CENTRAL' | 'SOUTH'
);

-- 2. customers ---------------------------------------------------------------
CREATE TABLE customers (
    customer_id  INTEGER PRIMARY KEY,
    full_name    TEXT NOT NULL,
    email        TEXT,                   -- SENSITIVE: denied by policy.yaml
    phone        TEXT,                   -- SENSITIVE: denied by policy.yaml
    segment      TEXT NOT NULL CHECK (segment IN ('retail', 'wholesale', 'vip')),
    status       TEXT NOT NULL CHECK (status IN ('active', 'inactive', 'churned')),
    region_id    INTEGER REFERENCES regions (region_id),
    created_at   TIMESTAMP NOT NULL
);

-- 3. addresses ---------------------------------------------------------------
CREATE TABLE addresses (
    address_id   INTEGER PRIMARY KEY,
    customer_id  INTEGER NOT NULL REFERENCES customers (customer_id),
    line1        TEXT NOT NULL,
    city         TEXT NOT NULL,          -- 'TP.HCM', 'Hà Nội', 'Đà Nẵng', ...
    region_id    INTEGER REFERENCES regions (region_id),
    is_default   BOOLEAN NOT NULL DEFAULT FALSE
);

-- 4. categories --------------------------------------------------------------
CREATE TABLE categories (
    category_id        INTEGER PRIMARY KEY,
    category_name      TEXT NOT NULL,
    parent_category_id INTEGER REFERENCES categories (category_id)
);

-- 5. suppliers ---------------------------------------------------------------
CREATE TABLE suppliers (
    supplier_id   INTEGER PRIMARY KEY,
    supplier_name TEXT NOT NULL,
    region_id     INTEGER REFERENCES regions (region_id),
    is_active     BOOLEAN NOT NULL DEFAULT TRUE
);

-- 6. products ----------------------------------------------------------------
CREATE TABLE products (
    product_id   INTEGER PRIMARY KEY,
    product_name TEXT NOT NULL,
    sku          TEXT NOT NULL UNIQUE,
    category_id  INTEGER REFERENCES categories (category_id),
    supplier_id  INTEGER REFERENCES suppliers (supplier_id),
    unit_price   NUMERIC(12, 2) NOT NULL,
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMP NOT NULL
);

-- 7. inventory ---------------------------------------------------------------
CREATE TABLE inventory (
    inventory_id  INTEGER PRIMARY KEY,
    product_id    INTEGER NOT NULL REFERENCES products (product_id),
    warehouse     TEXT NOT NULL,
    quantity      INTEGER NOT NULL,
    reorder_level INTEGER NOT NULL,
    updated_at    TIMESTAMP NOT NULL
);

-- 8. orders ------------------------------------------------------------------
CREATE TABLE orders (
    order_id     INTEGER PRIMARY KEY,
    customer_id  INTEGER NOT NULL REFERENCES customers (customer_id),
    status       TEXT NOT NULL CHECK (status IN ('pending', 'paid', 'shipped', 'completed', 'cancelled', 'refunded')),
    channel      TEXT NOT NULL CHECK (channel IN ('web', 'app', 'store', 'marketplace')),
    total_amount NUMERIC(14, 2) NOT NULL,
    discount     NUMERIC(14, 2) NOT NULL DEFAULT 0,
    created_at   TIMESTAMP NOT NULL,     -- order placed
    completed_at TIMESTAMP               -- fulfilment finished; NULL unless status='completed'
);

-- 9. order_items -------------------------------------------------------------
CREATE TABLE order_items (
    order_item_id INTEGER PRIMARY KEY,
    order_id      INTEGER NOT NULL REFERENCES orders (order_id),
    product_id    INTEGER NOT NULL REFERENCES products (product_id),
    quantity      INTEGER NOT NULL,
    unit_price    NUMERIC(12, 2) NOT NULL,
    line_total    NUMERIC(14, 2) NOT NULL
);

-- 10. payments ---------------------------------------------------------------
CREATE TABLE payments (
    payment_id INTEGER PRIMARY KEY,
    order_id   INTEGER NOT NULL REFERENCES orders (order_id),
    method     TEXT NOT NULL CHECK (method IN ('cod', 'card', 'bank_transfer', 'ewallet')),
    status     TEXT NOT NULL CHECK (status IN ('pending', 'succeeded', 'failed', 'refunded')),
    amount     NUMERIC(14, 2) NOT NULL,
    paid_at    TIMESTAMP                 -- money actually received; NULL unless status='succeeded'
);

-- 11. shipments --------------------------------------------------------------
CREATE TABLE shipments (
    shipment_id  INTEGER PRIMARY KEY,
    order_id     INTEGER NOT NULL REFERENCES orders (order_id),
    carrier      TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('created', 'in_transit', 'delivered', 'returned')),
    shipped_at   TIMESTAMP,
    delivered_at TIMESTAMP,
    address_id   INTEGER REFERENCES addresses (address_id)
);

-- 12. reviews ----------------------------------------------------------------
CREATE TABLE reviews (
    review_id   INTEGER PRIMARY KEY,
    product_id  INTEGER NOT NULL REFERENCES products (product_id),
    customer_id INTEGER NOT NULL REFERENCES customers (customer_id),
    rating      INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment     TEXT,
    created_at  TIMESTAMP NOT NULL
);
