"""High-concurrency race condition and oversell prevention tests."""

from __future__ import annotations

import concurrent.futures

from dukapulse.db.models import Inventory, Product
from dukapulse.services.inventory import InsufficientStockError, InventoryService


def test_oversell_blocked_single_thread(db_session):
    """Test standard single-thread oversell prevention."""
    service = InventoryService(db_session)
    shop_id = "shop_kibera_01"

    prod = db_session.query(Product).filter(Product.shop_id == shop_id).first()
    inv = db_session.query(Inventory).filter(Inventory.product_id == prod.id).first()

    # Set stock to exactly 3 units
    inv.current_stock = 3
    db_session.commit()

    # Attempt to sell 4 units
    try:
        service.process_sale(shop_id=shop_id, product_id=prod.id, quantity=4)
        assert False, "Should have raised InsufficientStockError"
    except InsufficientStockError as exc:
        assert exc.requested == 4
        assert exc.available == 3

    # Verify stock remained at 3
    db_session.refresh(inv)
    assert inv.current_stock == 3


def test_multi_threaded_concurrency_race_condition(tmp_path):
    """Simulate concurrent clerks trying to buy the last 5 items simultaneously."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from dukapulse.db.models import Base
    from dukapulse.seed import seed_database

    db_path = tmp_path / "concurrency_test.db"
    thread_engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"timeout": 30, "check_same_thread": False},
    )
    Base.metadata.create_all(bind=thread_engine)
    SessionLocal = sessionmaker(bind=thread_engine)

    shop_id = "shop_kibera_01"

    # Setup test product with exactly 5 items
    with SessionLocal() as init_sess:
        seed_database(init_sess, num_days=7)
        prod = init_sess.query(Product).filter(Product.shop_id == shop_id).first()
        prod_id = prod.id
        inv = init_sess.query(Inventory).filter(Inventory.product_id == prod_id).first()
        inv.current_stock = 5
        init_sess.commit()

    success_count = 0
    blocked_count = 0

    def attempt_sale(clerk_id: int):
        with SessionLocal() as worker_sess:
            service = InventoryService(worker_sess)
            try:
                service.process_sale(
                    shop_id=shop_id,
                    product_id=prod_id,
                    quantity=1,
                    cashier_id=f"clerk_{clerk_id}",
                )
                return True
            except InsufficientStockError:
                return False
            except Exception:
                return False

    # Execute simultaneous checkout requests
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(attempt_sale, i) for i in range(10)]
        for fut in concurrent.futures.as_completed(futures):
            if fut.result():
                success_count += 1
            else:
                blocked_count += 1

    # Exactly 5 units available, so at most 5 can ever succeed
    assert success_count == 5, f"Expected exactly 5 sales, got {success_count}"
    assert blocked_count == 5, f"Expected exactly 5 blocked transactions, got {blocked_count}"

    # Verify final stock is exactly 0 and never dropped negative
    with SessionLocal() as verify_sess:
        inv = verify_sess.query(Inventory).filter(Inventory.product_id == prod_id).first()
        assert inv.current_stock == 0
