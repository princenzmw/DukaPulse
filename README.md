---
title: DukaPulse Kiosk
emoji: 🏪
colorFrom: green
colorTo: blue
sdk: docker
app_port: 8000
pinned: false
---

# DukaPulse 🛒⚡

**Micro-retail inventory intelligence, oversell-proof concurrency locks, and honest demand forecasting for African neighborhood kiosks (dukas).**

Built for **MLH Global Hack Week: Builders Week** (November 2026).

[![CI](https://github.com/princenzmw/DukaPulse/actions/workflows/ci.yml/badge.svg)](https://github.com/princenzmw/DukaPulse/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![Tiger Data](https://img.shields.io/badge/Tiger%20Data-Timescale%20Hypertables-orange.svg)](https://www.timescale.com/)
[![pgvector](https://img.shields.io/badge/pgvector-384--d%20Semantic%20Search-teal.svg)](https://github.com/pgvector/pgvector)
[![Auth0](https://img.shields.io/badge/Auth0-RBAC%20%26%20JWT-red.svg)](https://auth0.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## 🌟 The Real-World Problem: The Informal Duka

In African urban and peri-urban neighborhoods (e.g. Kibera, Westlands, Eastleigh in Nairobi), informal retail kiosks (**dukas**) supply over 70% of fast-moving consumer goods (flour, cooking oil, milk, soap, airtime). 

However, kiosk owners face three compounding operational failures:
1. **The Over-Selling Hazard:** Physical shelf space is tight. When two clerks or mobile M-PESA orders claim the last item simultaneously, application memory race conditions sell phantom inventory, triggering customer disputes.
2. **Catalog Misalignment:** Product searches fail because customers and clerks use colloquial Kenyan terms (e.g., *"unga ya ugali"*, *"mafuta ya kupikia"*, *"sabuni ya kuoga"*) rather than formal manufacturing brand names.
3. **Guesswork Forecasting:** Small retailers over-order perishable goods or lock scarce working capital into slow-moving stock because predictive software is either absent or overfits on sparse kiosk transactions.

---

## 🏗️ Architecture & Core Innovations

```
                       ┌────────────────────────────────────────────────────────┐
                       │           Auth0 Identity & RBAC Layer                  │
                       │  (Claims: duka_owner vs duka_staff, RS256 JWKS)        │
                       └──────────────────────────┬─────────────────────────────┘
                                                  │
                 ┌────────────────────────────────┴──────────────────────────────┐
                 │                                                               │
                 ▼                                                               ▼
   ┌───────────────────────────┐                                   ┌───────────────────────────┐
   │    Streamlit Dashboard    │                                   │     FastAPI REST API      │
   │  (POS, Stock, Analytics)  │                                   │ (Pydantic v2, Dependency) │
   └─────────────┬─────────────┘                                   └─────────────┬─────────────┘
                 │                                                               │
                 └────────────────────────────────┬──────────────────────────────┘
                                                  │
                                                  ▼
                         ┌─────────────────────────────────────────────────┐
                         │            DukaPulse Core Engine                │
                         │  • Concurrency Guard (Pessimistic Row Locks)    │
                         │  • pgvector Cosine Semantic Retrieval           │
                         │  • Honest Forecasting Tournament Engine         │
                         └────────────────────────┬────────────────────────┘
                                                  │
                                                  ▼
                         ┌─────────────────────────────────────────────────┐
                         │        Tiger Data (Timescale) + PostgreSQL      │
                         │  • Multi-tenant Schemas (Shops, Products)       │
                         │  • sales_events (7-Day Hypertables)             │
                         │  • hourly_sales_summary (Continuous Aggregate)  │
                         │  • daily_duka_analytics (Continuous Aggregate)  │
                         │  • products.embedding (pgvector 384-d HNSW)     │
                         └─────────────────────────────────────────────────┘
```

### 1. Concurrency Lock: The Oversell-Proof Guarantee
When recording a sale, DukaPulse does not perform a vulnerable read-then-write in application memory. Instead, it acquires a **row-level pessimistic lock** directly in SQL:
```sql
SELECT * FROM inventory WHERE shop_id = :shop_id AND product_id = :product_id FOR UPDATE;
```
Combined with a table constraint `CONSTRAINT chk_stock_non_negative CHECK (current_stock >= 0)`, race conditions are physically blocked at the database engine level. If remaining stock is insufficient, the transaction immediately rolls back and raises an `InsufficientStockError` (HTTP 409 Conflict).

### 2. Tiger Data Hypertables & Continuous Aggregates
Every retail checkout emits an immutable event to `sales_events`. In high-volume retail, standard relational tables experience index bloat and slow aggregate queries. 
- **Hypertable Chunking:** `sales_events` is partitioned along `sale_time` into 7-day chunks via Tiger Data:
  ```sql
  SELECT create_hypertable('sales_events', 'sale_time', chunk_time_interval => INTERVAL '7 days');
  ```
- **Continuous Aggregates:** Real-time materialized rollups (`hourly_sales_summary`, `daily_duka_analytics`) continuously pre-calculate hourly rush profiles (7–9 AM morning tea & 5–8 PM evening supper rushes) and 30-day velocity with sub-millisecond query response times.

### 3. pgvector Semantic Search
Duka inventory is vectorized into a 384-dimensional dense semantic space with domain clustering across Kenyan staple goods. Queries like *"unga ya ugali"* semantically match `Jogoo Maize Meal 2kg` and `Pembe Maize Flour 2kg` with $>0.85$ cosine similarity:
```sql
SELECT p.id, p.name, p.unit_price, (1 - (p.embedding <=> :query_vec::vector)) AS similarity
FROM products p
ORDER BY p.embedding <=> :query_vec::vector ASC
LIMIT 5;
```

### 4. Honest Demand Forecasting: Seasonal-Naive Benchmarking
> *"A model only earns its compute budget if it proves lower Mean Absolute Percentage Error (MAPE) than repeating last cycle's demand."*

Rather than deploying black-box machine learning that overfits on sparse duka sales, DukaPulse runs an automated rolling backtest:
- **Baseline:** Seasonal-Naive ($F_{t+h} = Y_{t+h - m}$) repeating the prior 4-week sales cycle.
- **Challenger:** Holt's Linear Exponential Smoothing (Level + Trend).
- **Champion Rule:** The model calculates out-of-sample MAPE and MAE on a held-out 4-week window. If the challenger does not outperform the seasonal-naive baseline, DukaPulse automatically defaults to the baseline, safeguarding the merchant from over-stocking phantom demand.

### 5. Auth0 Identity & Role-Based Access Control (RBAC)
- **Token Verification:** RS256 JWKS verification against Auth0 domain endpoints with audience checking.
- **Roles:**
  - `duka_owner`: Unlocks wholesale purchase costs, profit margin analytics, reorder recommendations, and restock capabilities.
  - `duka_staff`: Access restricted to POS checkout and available inventory counts. Margin figures and restock mutations return `403 Forbidden`.
- **Offline / Grading Support:** Features an embedded developer token generator (`HS256`) so judges and CI pipelines can explore and evaluate both roles without external cloud dependencies.

---

## 🚀 Quickstart & Reproduction

### Prerequisites
- Python 3.11+
- (Optional) Docker & Docker Compose

### Option A: Local Python & Streamlit Dashboard (Immediate Run)
```bash
# 1. Clone the repository
git clone https://github.com/princenzmw/DukaPulse.git
cd DukaPulse

# 2. Create virtual environment & activate
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# 4. Run automated unit tests
pytest -v tests/

# 5. Launch interactive Kiosk Dashboard
streamlit run app/streamlit_app.py
```

### Option B: Full-Stack Docker Compose (Tiger Data + FastAPI + Streamlit)
```bash
# Launch Timescale / Tiger Data, FastAPI backend, and Streamlit frontend
docker compose up --build
```
- **Kiosk Dashboard:** `http://localhost:8501`
- **FastAPI OpenAPI Docs:** `http://localhost:8000/docs`
- **Tiger Data Database:** `localhost:5432` (`postgres:postgres`)

---

## 🧪 Automated Test Suite

DukaPulse includes 100% automated pytest coverage across critical operational pathways:
```text
tests/
├── test_concurrency.py       # Multi-threaded concurrent checkout race condition simulation
├── test_rbac.py              # Auth0 token verification, staff margin redaction & 403 blocks
├── test_semantic_search.py   # pgvector cosine similarity & Swahili/Sheng synonym retrieval
└── test_forecasting.py       # Seasonal-naive benchmark, Holt linear trend & MAPE calculation
```

Run tests with:
```bash
pytest -v tests/
```

---

## 📋 MLH Global Hack Week Challenge Receipts

| Challenge | Implementation Detail | Source File |
| :--- | :--- | :--- |
| **Tiger Data Hypertables** | `sales_events` partitioned on `sale_time` (7-day chunks) with continuous aggregate views | [`dukapulse/db/schema.sql`](dukapulse/db/schema.sql), [`timeseries.py`](dukapulse/services/timeseries.py) |
| **pgvector Embeddings** | 384-dimensional dense semantic vectors with cosine distance matching | [`dukapulse/services/semantic_search.py`](dukapulse/services/semantic_search.py) |
| **Auth0 Identity & RBAC** | RS256 JWKS token validation, `duka_owner` vs `duka_staff` roles | [`dukapulse/auth/jwt.py`](dukapulse/auth/jwt.py), [`dukapulse/auth/rbac.py`](dukapulse/auth/rbac.py) |

---

## 👤 Author & Maintainer
- **Prince NZAMUWE**
- GitHub: [@princenzmw](https://github.com/princenzmw)
- Portfolio: [nzamuwe.com](https://nzamuwe.com)
- Project Case Study: [nzamuwe.com/projects/dukapulse](https://nzamuwe.com/projects/dukapulse)
