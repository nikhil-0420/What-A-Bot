import json
import uuid
import pytest
from starlette.testclient import TestClient
from app.main import app
from app.db import get_conn


def test_owner_holds_real_data():
    with TestClient(app) as client:
        # 1. Login as owner
        login_resp = client.post("/auth/login", json={"email": "owner@demo.com", "password": "password123"})
        assert login_resp.status_code == 200
        token = login_resp.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        test_order_id = str(uuid.uuid4())
        test_booking_id = str(uuid.uuid4())
        test_session_id = str(uuid.uuid4())
        test_slot_id = str(uuid.uuid4())
        biz_retail = "demo-stationery-1"
        biz_service = "demo-services-1"

        with get_conn() as conn:
            with conn.transaction():
                conn.execute(
                    """
                    INSERT INTO sessions (session_id, customer_phone, destination, active_business_id)
                    VALUES (%s, '+919999999999', 'telegram_bot', %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (test_session_id, biz_retail),
                )
                conn.execute(
                    """
                    INSERT INTO inbox (input_id, source, session_id, business_id, body, status, attempts)
                    VALUES ('inp_hold_test', 'telegram', %s, %s, '{"text": "test"}'::jsonb, 'completed', 1)
                    ON CONFLICT (input_id) DO NOTHING
                    """,
                    (test_session_id, biz_retail),
                )
                items = json.dumps([{"sku": "A", "qty": 1, "unit_price_paise": 4000}])
                conn.execute(
                    """
                    INSERT INTO orders (order_id, quote_code, origin_input_id, session_id, business_id, status, total_paise, items, constraints)
                    VALUES (%s, 'Q123', 'inp_hold_test', %s, %s, 'held', 4000, %s, '{}'::jsonb)
                    """,
                    (test_order_id, test_session_id, biz_retail, items),
                )
                conn.execute(
                    """
                    INSERT INTO service_slots (slot_id, business_id, service_id, starts_at, capacity)
                    VALUES (%s, %s, 'srv-ac-repair', now(), 1)
                    """,
                    (test_slot_id, biz_service),
                )
                conn.execute(
                    """
                    INSERT INTO bookings (booking_id, slot_id, origin_input_id, session_id, business_id, status, total_paise)
                    VALUES (%s, %s, 'inp_hold_test', %s, %s, 'held', 49900)
                    """,
                    (test_booking_id, test_slot_id, test_session_id, biz_service),
                )

        try:
            # 2. GET /businesses/{id}/holds - verify retail held order returned
            resp_r = client.get(f"/businesses/{biz_retail}/holds", headers=headers)
            assert resp_r.status_code == 200
            holds_r = resp_r.json()
            hold_ids_r = [h["order_id"] for h in holds_r]
            assert test_order_id in hold_ids_r, f"Order {test_order_id} not found in holds: {hold_ids_r}"

            target_order = next(h for h in holds_r if h["order_id"] == test_order_id)
            assert target_order["status"] == "held"
            assert target_order["total_paise"] == 4000
            assert "created_at" in target_order

            # Verify service held booking returned
            resp_s = client.get(f"/businesses/{biz_service}/holds", headers=headers)
            assert resp_s.status_code == 200
            holds_s = resp_s.json()
            hold_ids_s = [h["order_id"] for h in holds_s]
            assert test_booking_id in hold_ids_s, f"Booking {test_booking_id} not found in holds: {hold_ids_s}"

            # 3. POST approve order
            appr_resp = client.post(
                f"/businesses/{biz_retail}/holds",
                json={"order_id": test_order_id, "approve": True},
                headers=headers,
            )
            assert appr_resp.status_code == 200
            appr_data = appr_resp.json()
            assert appr_data["status"] == "confirmed"

            # 4. POST reject booking
            rej_resp = client.post(
                f"/businesses/{biz_service}/holds",
                json={"order_id": test_booking_id, "approve": False},
                headers=headers,
            )
            assert rej_resp.status_code == 200
            rej_data = rej_resp.json()
            assert rej_data["status"] == "cancelled"

            # 5. GET /businesses/{id}/holds - now neither should be in 'held' state
            resp_after_r = client.get(f"/businesses/{biz_retail}/holds", headers=headers)
            assert resp_after_r.status_code == 200
            assert test_order_id not in [h["order_id"] for h in resp_after_r.json()]

            resp_after_s = client.get(f"/businesses/{biz_service}/holds", headers=headers)
            assert resp_after_s.status_code == 200
            assert test_booking_id not in [h["order_id"] for h in resp_after_s.json()]

            # 6. Auth checks
            resp_401 = client.get(f"/businesses/{biz_retail}/holds")
            assert resp_401.status_code == 401

            r_login = client.post("/auth/login", json={"email": "restricted@demo.com", "password": "password123"})
            r_headers = {"Authorization": f"Bearer {r_login.json()['token']}"}
            resp_403 = client.get("/businesses/demo-supermarket-1/holds", headers=r_headers)
            assert resp_403.status_code == 403

        finally:
            # Clean up test rows
            with get_conn() as conn:
                with conn.transaction():
                    conn.execute("DELETE FROM invoices WHERE order_id = %s", (test_order_id,))
                    conn.execute("DELETE FROM orders WHERE order_id = %s", (test_order_id,))
                    conn.execute("DELETE FROM bookings WHERE booking_id = %s", (test_booking_id,))
                    conn.execute("DELETE FROM service_slots WHERE slot_id = %s", (test_slot_id,))
                    conn.execute("DELETE FROM inbox WHERE input_id = 'inp_hold_test'")
                    conn.execute("DELETE FROM sessions WHERE session_id = %s", (test_session_id,))
                    # Restore stock for sku A if decremented
                    conn.execute("UPDATE catalog SET qty = qty + 1 WHERE business_id = %s AND sku = 'A'", (biz_retail,))
