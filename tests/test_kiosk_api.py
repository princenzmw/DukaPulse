"""Unit tests for Kiosk API endpoints on SQLite fallback."""

from __future__ import annotations

from dukapulse.db.models import Product


def test_search_ranks_unga_jogoo(client):
    """GET /api/products/search?q=unga ranks Jogoo Maize Meal in top hits."""
    res = client.get("/api/products/search?q=unga&k=5")
    assert res.status_code == 200
    items = res.json()
    assert len(items) > 0

    # Ensure Jogoo Maize Meal or Pembe Maize Flour is present in top hits
    product_names = [it["name"] for it in items]
    assert any("Jogoo" in name or "Maize" in name for name in product_names), (
        f"Expected Jogoo/Maize in top search results, got: {product_names}"
    )
    # Ensure ordered by similarity descending
    sims = [it["similarity"] for it in items]
    assert sims == sorted(sims, reverse=True)


def test_demo_oversell_race_endpoint(client, db_session):
    """POST /api/demo/oversell-race returns exactly one success and one 409."""
    prod = db_session.query(Product).first()
    assert prod is not None

    payload = {"product_id": prod.id, "shop_id": "shop_kibera_01"}
    res = client.post("/api/demo/oversell-race", json=payload)
    assert res.status_code == 200
    data = res.json()
    attempts = data["attempts"]
    assert len(attempts) == 2

    outcomes = [a["outcome"] for a in attempts]
    assert "success" in outcomes
    assert "rejected" in outcomes

    success_attempt = next(a for a in attempts if a["outcome"] == "success")
    assert success_attempt["status_code"] == 200
    assert success_attempt["remaining_stock"] == 0

    rejected_attempt = next(a for a in attempts if a["outcome"] == "rejected")
    assert rejected_attempt["status_code"] == 409
    assert "error" in rejected_attempt


def test_staff_restock_forbidden(client, staff_token, db_session):
    """Staff role is forbidden from restocking (HTTP 403)."""
    prod = db_session.query(Product).first()
    headers = {"Authorization": f"Bearer {staff_token}"}
    payload = {
        "shop_id": "shop_kibera_01",
        "product_id": prod.id,
        "quantity": 10,
    }
    res = client.post("/api/inventory/restock", json=payload, headers=headers)
    assert res.status_code == 403
    assert "Forbidden" in res.json()["detail"]


def test_staff_product_list_margin_redacted(client, staff_token, owner_token):
    """Staff sees product list with margin_ksh == None; Owner sees numeric margin."""
    # Staff request
    staff_res = client.get(
        "/api/products?shop_id=shop_kibera_01",
        headers={"Authorization": f"Bearer {staff_token}"},
    )
    assert staff_res.status_code == 200
    staff_items = staff_res.json()
    assert len(staff_items) > 0
    for it in staff_items:
        assert it["margin_ksh"] is None
        assert "price_ksh" in it
        assert "stock" in it

    # Owner request
    owner_res = client.get(
        "/api/products?shop_id=shop_kibera_01",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert owner_res.status_code == 200
    owner_items = owner_res.json()
    assert len(owner_items) > 0
    first_owner = owner_items[0]
    assert first_owner["margin_ksh"] is not None
    assert isinstance(first_owner["margin_ksh"], (int, float))


def test_kiosk_html_endpoint(client):
    """GET /kiosk returns 200 and contains 'DUKAPULSE'."""
    res = client.get("/kiosk")
    # Starlette static files redirects /kiosk to /kiosk/
    if res.status_code in (301, 307):
        res = client.get("/kiosk/")
    assert res.status_code == 200
    assert "DUKAPULSE" in res.text


def test_healthcheck_endpoint(client):
    """GET /health returns minimal public status payload."""
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["database"] == "connected"
    assert data["service"] == "DukaPulse"
    assert "version" in data
    assert set(data.keys()) == {"status", "database", "service", "version"}
