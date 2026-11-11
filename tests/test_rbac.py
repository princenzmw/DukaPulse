"""Auth0 authentication and role-based access control tests."""

from __future__ import annotations


def test_unauthenticated_request_fails(client):
    """Endpoints require Bearer token."""
    res = client.get("/api/inventory?shop_id=shop_kibera_01")
    assert res.status_code == 401


def test_staff_cannot_restock(client, staff_token):
    """Staff role is blocked from restocking (HTTP 403 Forbidden)."""
    headers = {"Authorization": f"Bearer {staff_token}"}
    payload = {
        "shop_id": "shop_kibera_01",
        "product_id": "dummy_id",
        "quantity": 10,
    }
    res = client.post("/api/inventory/restock", json=payload, headers=headers)
    assert res.status_code == 403
    assert "Forbidden" in res.json()["detail"]


def test_owner_can_restock(client, owner_token, db_session):
    """Owner role can restock inventory (HTTP 200 OK)."""
    from dukapulse.db.models import Product

    prod = db_session.query(Product).first()

    headers = {"Authorization": f"Bearer {owner_token}"}
    payload = {
        "shop_id": "shop_kibera_01",
        "product_id": prod.id,
        "quantity": 12,
    }
    res = client.post("/api/inventory/restock", json=payload, headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["units_added"] == 12


def test_staff_margin_redaction(client, staff_token, owner_token):
    """Staff sees stock but margin metrics are redacted; Owner sees full financial margins."""
    # Staff request
    staff_res = client.get(
        "/api/inventory?shop_id=shop_kibera_01",
        headers={"Authorization": f"Bearer {staff_token}"},
    )
    assert staff_res.status_code == 200
    staff_data = staff_res.json()
    assert staff_data["role_applied"] == "staff"
    first_item = staff_data["inventory"][0]
    assert first_item["margin_kes"] is None
    assert first_item["unit_cost"] is None

    # Owner request
    owner_res = client.get(
        "/api/inventory?shop_id=shop_kibera_01",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert owner_res.status_code == 200
    owner_data = owner_res.json()
    assert owner_data["role_applied"] == "owner"
    first_owner_item = owner_data["inventory"][0]
    assert first_owner_item["margin_kes"] is not None
    assert first_owner_item["unit_cost"] is not None
