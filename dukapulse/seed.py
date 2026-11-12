"""Authentic Nairobi Duka Seed Data Generator.

Populates multi-tenant shops, real Kenyan consumer goods, pgvector embeddings,
and 60 days of time-series sales transactions for Tiger Data hypertables.
"""

from __future__ import annotations

import datetime
import json
import random
import uuid

from sqlalchemy.orm import Session

from .db.models import HAS_PGVECTOR, Inventory, Product, SalesEvent, Shop
from .db.session import SessionLocal, init_db
from .services.semantic_search import compute_dense_embedding

PRODUCTS_CATALOG = [
    {
        "name": "Jogoo Maize Meal 2kg",
        "category": "Flour & Grains",
        "unit_cost": 185.0,
        "unit_price": 215.0,
        "barcode": "616110123451",
        "description": "Grade 1 sifted maize meal for cooking ugali, staple Kenyan household food. unga ya ugali",
        "initial_stock": 45,
        "reorder_point": 15,
        "reorder_qty": 30,
        "daily_avg_sales": 8,
    },
    {
        "name": "Pembe Maize Flour 2kg",
        "category": "Flour & Grains",
        "unit_cost": 180.0,
        "unit_price": 210.0,
        "barcode": "616110123452",
        "description": "Sifted white maize meal flour for soft ugali. unga wa ugali",
        "initial_stock": 35,
        "reorder_point": 12,
        "reorder_qty": 24,
        "daily_avg_sales": 6,
    },
    {
        "name": "Rina Salad Cooking Oil 1L",
        "category": "Cooking Oil & Fats",
        "unit_cost": 260.0,
        "unit_price": 300.0,
        "barcode": "616110234561",
        "description": "Triple refined pure vegetable cooking oil, mafuta ya kupikia. cooking oil",
        "initial_stock": 25,
        "reorder_point": 8,
        "reorder_qty": 20,
        "daily_avg_sales": 4,
    },
    {
        "name": "Fresh Fri Cooking Oil 2L",
        "category": "Cooking Oil & Fats",
        "unit_cost": 520.0,
        "unit_price": 590.0,
        "barcode": "616110234562",
        "description": "Premium vegetable frying and cooking oil with ginger flavour. mafuta ya kupika",
        "initial_stock": 18,
        "reorder_point": 6,
        "reorder_qty": 12,
        "daily_avg_sales": 3,
    },
    {
        "name": "KCC Fresh Homogenized Milk 500ml",
        "category": "Dairy & Bread",
        "unit_cost": 55.0,
        "unit_price": 65.0,
        "barcode": "616110345671",
        "description": "Pasteurized fresh cow milk, maziwa ya fresh for morning tea.",
        "initial_stock": 60,
        "reorder_point": 20,
        "reorder_qty": 48,
        "daily_avg_sales": 14,
    },
    {
        "name": "Brookside Long Life Milk 500ml",
        "category": "Dairy & Bread",
        "unit_cost": 62.0,
        "unit_price": 72.0,
        "barcode": "616110345672",
        "description": "UHT whole milk tetrapak, ambient shelf-stable.",
        "initial_stock": 30,
        "reorder_point": 10,
        "reorder_qty": 24,
        "daily_avg_sales": 5,
    },
    {
        "name": "Broadways White Bread 400g",
        "category": "Dairy & Bread",
        "unit_cost": 60.0,
        "unit_price": 70.0,
        "barcode": "616110456781",
        "description": "Freshly baked sliced white sandwich bread.",
        "initial_stock": 28,
        "reorder_point": 10,
        "reorder_qty": 20,
        "daily_avg_sales": 9,
    },
    {
        "name": "Omo Hand Washing Powder 500g",
        "category": "Household & Cleaning",
        "unit_cost": 175.0,
        "unit_price": 205.0,
        "barcode": "616110567891",
        "description": "Laundry washing powder detergent with active foam for clothes stain removal, sabuni ya kuosha fabric.",
        "initial_stock": 20,
        "reorder_point": 8,
        "reorder_qty": 15,
        "daily_avg_sales": 3,
    },
    {
        "name": "Geisha Bath Soap 225g Aloe Vera",
        "category": "Personal Care",
        "unit_cost": 95.0,
        "unit_price": 115.0,
        "barcode": "616110678901",
        "description": "Long lasting green beauty bar soap with natural extracts, sabuni ya kuoga bath soap.",
        "initial_stock": 40,
        "reorder_point": 12,
        "reorder_qty": 24,
        "daily_avg_sales": 7,
    },
    {
        "name": "Royco Mchuzi Mix Beef 200g",
        "category": "Dry Goods & Spices",
        "unit_cost": 85.0,
        "unit_price": 100.0,
        "barcode": "616110789012",
        "description": "Food seasoning and beef flavour gravy thickener for stews.",
        "initial_stock": 35,
        "reorder_point": 10,
        "reorder_qty": 24,
        "daily_avg_sales": 6,
    },
    {
        "name": "Ketepa Pride Tea Bags 50s",
        "category": "Dry Goods & Spices",
        "unit_cost": 130.0,
        "unit_price": 155.0,
        "barcode": "616110890123",
        "description": "Pure Kenya black tea blend in teabags, chai ya majani.",
        "initial_stock": 22,
        "reorder_point": 8,
        "reorder_qty": 16,
        "daily_avg_sales": 4,
    },
    {
        "name": "Safaricom Airtime KES 50",
        "category": "Telecom",
        "unit_cost": 47.0,
        "unit_price": 50.0,
        "barcode": "616110901234",
        "description": "Prepaid mobile airtime scratch card 50 shillings.",
        "initial_stock": 100,
        "reorder_point": 25,
        "reorder_qty": 50,
        "daily_avg_sales": 18,
    },
    {
        "name": "Safaricom Airtime KES 100",
        "category": "Telecom",
        "unit_cost": 94.0,
        "unit_price": 100.0,
        "barcode": "616110901235",
        "description": "Prepaid mobile airtime scratch card 100 shillings.",
        "initial_stock": 80,
        "reorder_point": 20,
        "reorder_qty": 40,
        "daily_avg_sales": 12,
    },
    {
        "name": "Daawat Traditional Basmati Rice 1kg",
        "category": "Flour & Grains",
        "unit_cost": 240.0,
        "unit_price": 285.0,
        "barcode": "616110901236",
        "description": "Aromatic long grain white basmati rice.",
        "initial_stock": 20,
        "reorder_point": 6,
        "reorder_qty": 15,
        "daily_avg_sales": 3,
    },
]


def seed_database(db: Session, num_days: int = 60, seed: int = 42) -> str:
    """Populate tenant shops, catalog with pgvector embeddings, and time-series history."""
    random.seed(seed)

    # 1. Ensure Shop exists
    shop_id = "shop_kibera_01"
    shop = db.query(Shop).filter(Shop.id == shop_id).first()
    if not shop:
        shop = Shop(
            id=shop_id,
            name="Mama Sarah Kiosk - Olympic, Kibera",
            owner_id="auth0|prince_owner_789",
            currency="KES",
            location="Olympic Stage, Kibera, Nairobi",
        )
        db.add(shop)
        db.commit()

    # 2. Add products and inventory
    product_records = []
    for item in PRODUCTS_CATALOG:
        prod = (
            db.query(Product)
            .filter(Product.shop_id == shop_id, Product.barcode == item["barcode"])
            .first()
        )
        emb_list = compute_dense_embedding(
            f"{item['name']} {item['description']} {item['category']}"
        )

        if not prod:
            prod_id = str(uuid.uuid4())
            emb_field = emb_list if HAS_PGVECTOR else json.dumps(emb_list)
            prod = Product(
                id=prod_id,
                shop_id=shop_id,
                barcode=item["barcode"],
                name=item["name"],
                category=item["category"],
                unit_cost=item["unit_cost"],
                unit_price=item["unit_price"],
                description=item["description"],
                embedding=emb_field,
            )
            db.add(prod)
            db.flush()

            inv = Inventory(
                shop_id=shop_id,
                product_id=prod.id,
                current_stock=item["initial_stock"],
                reorder_point=item["reorder_point"],
                reorder_quantity=item["reorder_qty"],
            )
            db.add(inv)
        product_records.append((prod, item))

    db.commit()

    # 3. Generate 60 days of historical sales events if empty
    existing_events = db.query(SalesEvent).filter(SalesEvent.shop_id == shop_id).count()
    if existing_events == 0:
        now = datetime.datetime.now(datetime.UTC)
        start_time = now - datetime.timedelta(days=num_days)

        events_to_insert = []
        for day_offset in range(num_days):
            current_day = start_time + datetime.timedelta(days=day_offset)
            is_weekend = current_day.weekday() in (4, 5)  # Friday & Saturday peak shopping
            day_multiplier = 1.35 if is_weekend else 1.0

            for prod, item in product_records:
                base_sales = item["daily_avg_sales"]
                # Add weekly seasonal wave + random noise
                num_tx = max(0, int(random.gauss(base_sales * day_multiplier, 1.8)))
                for _ in range(num_tx):
                    # Kiosk peak hours: Morning (7-9 AM) or Evening (5-8 PM)
                    if random.random() < 0.45:
                        hour = random.choice([7, 8, 9])
                    elif random.random() < 0.80:
                        hour = random.choice([17, 18, 19, 20])
                    else:
                        hour = random.randint(10, 16)

                    minute = random.randint(0, 59)
                    second = random.randint(0, 59)
                    tx_time = current_day.replace(hour=hour, minute=minute, second=second)

                    qty = random.choice([1, 1, 1, 2])
                    rev = round(prod.unit_price * qty, 2)
                    cost = round(prod.unit_cost * qty, 2)
                    prof = round(rev - cost, 2)
                    method = "M-PESA" if random.random() < 0.72 else "CASH"

                    event = SalesEvent(
                        id=str(uuid.uuid4()),
                        sale_time=tx_time,
                        shop_id=shop_id,
                        product_id=prod.id,
                        product_name=prod.name,
                        quantity=qty,
                        unit_cost=prod.unit_cost,
                        unit_price=prod.unit_price,
                        total_revenue=rev,
                        profit=prof,
                        payment_method=method,
                        cashier_id="staff_kiosk_01",
                    )
                    events_to_insert.append(event)

        db.bulk_save_objects(events_to_insert)
        db.commit()

    return shop_id


if __name__ == "__main__":
    init_db()
    with SessionLocal() as db_session:
        sid = seed_database(db_session)
        print(f"Successfully initialized and seeded DukaPulse for shop: {sid}")
