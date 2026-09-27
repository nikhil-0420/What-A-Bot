import pytest
from starlette.testclient import TestClient
from app.main import app


def test_catalog_retail_and_service():
    with TestClient(app) as client:
        # 1. Login as owner
        login_resp = client.post("/auth/login", json={"email": "owner@demo.com", "password": "password123"})
        assert login_resp.status_code == 200
        token = login_resp.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 2. Retail business catalog
        resp_retail = client.get("/businesses/demo-stationery-1/catalog", headers=headers)
        assert resp_retail.status_code == 200
        items_retail = resp_retail.json()
        assert len(items_retail) >= 4
        # Verify CONTRACTS.md schema
        first = items_retail[0]
        for field in ("sku", "name", "brand", "ruling", "size", "price_paise", "qty"):
            assert field in first, f"Missing field {field} in catalog item"
        assert first["sku"] == "A"
        assert first["price_paise"] == 4000
        assert first["qty"] == 50

        # 3. Service business catalog
        resp_service = client.get("/businesses/demo-services-1/catalog", headers=headers)
        assert resp_service.status_code == 200
        items_service = resp_service.json()
        assert len(items_service) >= 3
        s_first = items_service[0]
        for field in ("sku", "name", "brand", "ruling", "size", "price_paise", "qty"):
            assert field in s_first, f"Missing field {field} in service-catalog item"
        assert s_first["sku"] == "srv-ac-repair"
        assert s_first["price_paise"] == 49900

        # 4. Non-existent business -> 404
        resp_404 = client.get("/businesses/non-existent-biz-id/catalog", headers=headers)
        assert resp_404.status_code == 404
        assert resp_404.json()["error"]["code"] == "not_found"

        # 5. Restricted owner access forbidden -> 403
        r_login = client.post("/auth/login", json={"email": "restricted@demo.com", "password": "password123"})
        r_token = r_login.json()["token"]
        r_headers = {"Authorization": f"Bearer {r_token}"}
        resp_403 = client.get("/businesses/demo-supermarket-1/catalog", headers=r_headers)
        assert resp_403.status_code == 403
        assert resp_403.json()["error"]["code"] == "forbidden"

        # 6. Unauthorized -> 401
        resp_401 = client.get("/businesses/demo-stationery-1/catalog")
        assert resp_401.status_code == 401
