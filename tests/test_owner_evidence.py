import json
import uuid
import pytest
from starlette.testclient import TestClient
from app.main import app
from app.db import get_conn


def test_owner_evidence_real_data():
    with TestClient(app) as client:
        # 1. Login as owner
        login_resp = client.post("/auth/login", json={"email": "owner@demo.com", "password": "password123"})
        assert login_resp.status_code == 200
        token = login_resp.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        biz_id = "demo-stationery-1"

        # 2. Query evidence for demo-stationery-1
        resp = client.get(f"/businesses/{biz_id}/evidence", headers=headers)
        assert resp.status_code == 200
        evidence_list = resp.json()
        assert isinstance(evidence_list, list)
        assert len(evidence_list) >= 1

        primary = evidence_list[0]
        # Verify Section L fields
        required_fields = [
            "normalized_constraints",
            "candidate_rows",
            "model_selected_quantities",
            "validation_result",
            "order_id",
            "order_status",
            "stock_before",
            "stock_after",
            "stock_before_after",
            "outbox_state",
            "latency_ms",
            "cost_usd",
        ]
        for field in required_fields:
            assert field in primary, f"Missing Section L field '{field}' in evidence response"

        assert isinstance(primary["normalized_constraints"], dict)
        assert isinstance(primary["candidate_rows"], list)
        assert len(primary["candidate_rows"]) >= 4
        assert isinstance(primary["model_selected_quantities"], list)
        assert "PASS" in primary["validation_result"]

        # 3. Test with a real order in DB to verify live order reflection
        test_order_id = str(uuid.uuid4())
        test_session_id = str(uuid.uuid4())
        with get_conn() as conn:
            with conn.transaction():
                conn.execute(
                    """
                    INSERT INTO sessions (session_id, customer_phone, destination, active_business_id)
                    VALUES (%s, '+919999999999', 'telegram_bot', %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (test_session_id, biz_id),
                )
                conn.execute(
                    """
                    INSERT INTO inbox (input_id, source, session_id, business_id, body, status, attempts)
                    VALUES ('inp_ev_test', 'telegram', %s, %s, '{"text": "evidence test"}'::jsonb, 'completed', 1)
                    ON CONFLICT (input_id) DO NOTHING
                    """,
                    (test_session_id, biz_id),
                )
                items = json.dumps([{"sku": "A", "qty": 2, "unit_price_paise": 4000}])
                constraints = json.dumps({"quantity": 2, "budget_paise": 10000, "ruling": "ruled", "size": "A5"})
                conn.execute(
                    """
                    INSERT INTO orders (order_id, quote_code, origin_input_id, session_id, business_id, status, total_paise, items, constraints)
                    VALUES (%s, 'Q_EV_TEST', 'inp_ev_test', %s, %s, 'confirmed', 8000, %s, %s)
                    """,
                    (test_order_id, test_session_id, biz_id, items, constraints),
                )

        try:
            resp_order = client.get(f"/businesses/{biz_id}/evidence", headers=headers)
            assert resp_order.status_code == 200
            ord_evidence = resp_order.json()[0]
            assert ord_evidence["order_id"] == test_order_id
            assert ord_evidence["quote_code"] == "Q_EV_TEST"
            assert ord_evidence["order_status"] == "confirmed"
            assert ord_evidence["normalized_constraints"]["quantity"] == 2
            assert ord_evidence["model_selected_quantities"][0]["sku"] == "A"
        finally:
            with get_conn() as conn:
                with conn.transaction():
                    conn.execute("DELETE FROM orders WHERE order_id = %s", (test_order_id,))
                    conn.execute("DELETE FROM inbox WHERE input_id = 'inp_ev_test'")
                    conn.execute("DELETE FROM sessions WHERE session_id = %s", (test_session_id,))

        # 4. Auth & Error handling
        resp_401 = client.get(f"/businesses/{biz_id}/evidence")
        assert resp_401.status_code == 401

        r_login = client.post("/auth/login", json={"email": "restricted@demo.com", "password": "password123"})
        r_headers = {"Authorization": f"Bearer {r_login.json()['token']}"}
        resp_403 = client.get("/businesses/demo-supermarket-1/evidence", headers=r_headers)
        assert resp_403.status_code == 403

        resp_404 = client.get("/businesses/non-existent-biz/evidence", headers=headers)
        assert resp_404.status_code == 404
