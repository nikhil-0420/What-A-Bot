import hashlib
import hmac
import json
import pytest
from starlette.testclient import TestClient
from app.main import app
from app.config import settings
from app.db import get_conn


def test_owner_billing_checkout_and_status():
    with TestClient(app) as client:
        # 1. Login as owner
        login_resp = client.post("/auth/login", json={"email": "owner@demo.com", "password": "password123"})
        assert login_resp.status_code == 200
        token = login_resp.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        biz_id = "demo-stationery-1"

        # 2. Status initially (trial)
        status_resp = client.get(f"/businesses/{biz_id}/billing/status", headers=headers)
        assert status_resp.status_code == 200
        status_data = status_resp.json()
        assert "plan" in status_data
        assert "updated_at" in status_data

        # 3. Create checkout
        checkout_resp = client.post(f"/businesses/{biz_id}/billing/checkout", headers=headers)
        assert checkout_resp.status_code == 200
        checkout_data = checkout_resp.json()
        assert "checkout_url" in checkout_data
        assert "dodopayments.com" in checkout_data["checkout_url"]

        # 4. Verify billing event was recorded in DB
        with get_conn() as conn:
            event_row = conn.execute(
                "SELECT kind, status FROM billing_events WHERE business_id = %s ORDER BY created_at DESC LIMIT 1",
                (biz_id,),
            ).fetchone()
            assert event_row is not None
            assert event_row[0] == "checkout_initiated"

        # 5. Simulate Dodo webhook payment.succeeded
        webhook_payload = json.dumps({
            "event_id": "dodo_test_evt_123",
            "event_type": "payment.succeeded",
            "data": {
                "metadata": {"business_id": biz_id}
            }
        }).encode("utf-8")

        secret = settings.dodo_webhook_secret or "test_secret"
        # Temporarily ensure a secret if blank
        orig_secret = settings.dodo_webhook_secret
        if not orig_secret:
            settings.dodo_webhook_secret = "test_webhook_secret"
            secret = settings.dodo_webhook_secret

        try:
            signature = hmac.new(secret.encode("utf-8"), webhook_payload, hashlib.sha256).hexdigest()
            wh_resp = client.post(
                "/webhook/dodo",
                content=webhook_payload,
                headers={"Dodo-Signature": signature, "Content-Type": "application/json"},
            )
            assert wh_resp.status_code == 200
            assert wh_resp.json()["status"] == "success"

            # Check status updated to test_paid
            status_after = client.get(f"/businesses/{biz_id}/billing/status", headers=headers)
            assert status_after.status_code == 200
            assert status_after.json()["plan"] == "test_paid"
        finally:
            settings.dodo_webhook_secret = orig_secret
            with get_conn() as conn:
                with conn.transaction():
                    conn.execute("DELETE FROM billing_events WHERE dodo_event_id IN ('dodo_test_evt_123') OR kind = 'checkout_initiated'")
                    conn.execute("UPDATE business_plan SET plan = 'trial' WHERE business_id = %s", (biz_id,))

        # 6. Auth checks
        resp_401 = client.post(f"/businesses/{biz_id}/billing/checkout")
        assert resp_401.status_code == 401

        r_login = client.post("/auth/login", json={"email": "restricted@demo.com", "password": "password123"})
        r_headers = {"Authorization": f"Bearer {r_login.json()['token']}"}
        resp_403 = client.post("/businesses/demo-supermarket-1/billing/checkout", headers=r_headers)
        assert resp_403.status_code == 403

        resp_404 = client.post("/businesses/non-existent-biz/billing/checkout", headers=headers)
        assert resp_404.status_code == 404
