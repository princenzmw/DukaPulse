-- ==============================================================================
-- DUKAPULSE: TIGER DATA (TIMESCALE) & PGVECTOR SCHEMA SETUP
-- MLH Global Hack Week: Builders Week Challenge
-- ==============================================================================

-- 1. Enable Tiger Data / Timescale & pgvector Extensions
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
CREATE EXTENSION IF NOT EXISTS vector CASCADE;

-- 2. Shops Table (Multi-Tenant Isolation)
CREATE TABLE IF NOT EXISTS shops (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    owner_id VARCHAR(120) NOT NULL,
    currency VARCHAR(3) DEFAULT 'KES',
    location VARCHAR(120) DEFAULT 'Nairobi, Kenya',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_shops_owner ON shops(owner_id);

-- 3. Products Table with pgvector Semantic Embeddings (384 dimensions)
CREATE TABLE IF NOT EXISTS products (
    id VARCHAR(36) PRIMARY KEY,
    shop_id VARCHAR(36) NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
    barcode VARCHAR(64),
    name VARCHAR(150) NOT NULL,
    category VARCHAR(60) NOT NULL,
    unit_cost NUMERIC(10, 2) NOT NULL,
    unit_price NUMERIC(10, 2) NOT NULL,
    description TEXT,
    embedding vector(384),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_products_shop ON products(shop_id);
CREATE INDEX IF NOT EXISTS idx_products_barcode ON products(barcode);

-- pgvector Index: Cosine Distance for Fast Kiosk Product Retrieval
-- Matches Kenyan colloquial queries ("unga", "mafuta", "sabuni ya kuoga", "omo")
CREATE INDEX IF NOT EXISTS idx_products_embedding_hnsw 
ON products USING hnsw (embedding vector_cosine_ops);

-- 4. Inventory Table with Invariant Concurrency Check Constraint
CREATE TABLE IF NOT EXISTS inventory (
    id VARCHAR(36) PRIMARY KEY,
    shop_id VARCHAR(36) NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
    product_id VARCHAR(36) NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    current_stock INT NOT NULL DEFAULT 0,
    reorder_point INT NOT NULL DEFAULT 10,
    reorder_quantity INT NOT NULL DEFAULT 24,
    last_restocked_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_shop_product_inventory UNIQUE (shop_id, product_id),
    CONSTRAINT chk_stock_non_negative CHECK (current_stock >= 0)
);

-- 5. Sales Events Table (Raw Time-Series Ledger)
CREATE TABLE IF NOT EXISTS sales_events (
    id VARCHAR(36) NOT NULL,
    sale_time TIMESTAMPTZ NOT NULL,
    shop_id VARCHAR(36) NOT NULL,
    product_id VARCHAR(36) NOT NULL,
    product_name VARCHAR(150) NOT NULL,
    quantity INT NOT NULL CHECK (quantity > 0),
    unit_cost NUMERIC(10, 2) NOT NULL,
    unit_price NUMERIC(10, 2) NOT NULL,
    total_revenue NUMERIC(10, 2) NOT NULL,
    profit NUMERIC(10, 2) NOT NULL,
    payment_method VARCHAR(30) DEFAULT 'M-PESA',
    cashier_id VARCHAR(120) DEFAULT 'staff_kiosk',
    PRIMARY KEY (id, sale_time)
);

-- 6. Turn sales_events into a Tiger Data Hypertable
-- Partitions data by time chunks for high-throughput write performance & instant time queries
SELECT create_hypertable(
    'sales_events',
    'sale_time',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

-- 7. Tiger Data Continuous Aggregate: Hourly Sales Summary
CREATE MATERIALIZED VIEW IF NOT EXISTS hourly_sales_summary
WITH (timescaledb.continuous) AS
SELECT 
    time_bucket('1 hour', sale_time) AS bucket,
    shop_id,
    product_id,
    product_name,
    SUM(quantity) AS units_sold,
    SUM(total_revenue) AS revenue,
    SUM(profit) AS net_profit,
    COUNT(*) AS transaction_count
FROM sales_events
GROUP BY bucket, shop_id, product_id, product_name
WITH NO DATA;

-- 8. Tiger Data Continuous Aggregate: Daily Duka Rollup
CREATE MATERIALIZED VIEW IF NOT EXISTS daily_duka_analytics
WITH (timescaledb.continuous) AS
SELECT 
    time_bucket('1 day', sale_time) AS bucket,
    shop_id,
    SUM(quantity) AS total_units_sold,
    SUM(total_revenue) AS gross_revenue,
    SUM(profit) AS total_profit,
    COUNT(DISTINCT product_id) AS distinct_products_sold,
    COUNT(*) AS total_sales_receipts
FROM sales_events
GROUP BY bucket, shop_id
WITH NO DATA;

-- 9. Refresh Continuous Aggregates Policy
SELECT add_continuous_aggregate_policy('hourly_sales_summary',
    start_offset => INTERVAL '1 month',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '30 minutes',
    if_not_exists => TRUE
);

SELECT add_continuous_aggregate_policy('daily_duka_analytics',
    start_offset => INTERVAL '3 months',
    end_offset => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE
);
