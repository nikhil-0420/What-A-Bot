import json
import uuid
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.config import settings
from app.db import get_conn, init_pool, close_pool
from app.bot_link import issue_token, consume_token
from app.dispatcher import _process_one, retry_attention_row, dispatch_due_batch
from app.sender import _redact_token, send_one_pending
from app.n8n import notify_hold


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    init_pool()
    yield
    close_pool()


@pytest.fixture
def client():
    return TestClient(app)


def test_health_success(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_failure_returns_503(client):
    with patch("app.main.health_ping", return_value=False):
        resp = client.get("/health")
        assert resp.status_code == 503
        assert resp.json() == {"status": "error", "message": "Database ping failed"}


def test_token_redaction():
    fake_token = settings.telegram_bot_token
    sample = f"https://api.telegram.org/bot{fake_token}/sendMessage"
    redacted = _redact_token(sample)
    assert fake_token not in redacted
    assert "[REDACTED_BOT_TOKEN]" in redacted


def test_sender_rejects_ok_false():
    outbox_id = str(uuid.uuid4())
    event_key = f"test:ok_false:{outbox_id}"

    with get_conn() as conn:
        with conn.transaction():
            conn.execute(
                """
                INSERT INTO outbox (outbox_id, event_key, payload, state)
                VALUES (%s, %s, %s, 'pending')
                """,
                (outbox_id, event_key, json.dumps({"to": "12345", "text": "test"})),
            )

    # Mock Telegram returning 200 but ok=False
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"ok": False, "description": "Chat not found"}
    mock_resp.text = json.dumps({"ok": False, "description": "Chat not found"})

    with patch("app.config.settings.send_mode", "real"):
        with patch("httpx.AsyncClient.post", return_value=mock_resp):
            async def run_send():
                return await send_one_pending()

            import asyncio
            asyncio.run(run_send())

    with get_conn() as conn:
        row = conn.execute(
            "SELECT state FROM outbox WHERE outbox_id = %s",
            (outbox_id,),
        ).fetchone()
        assert row is not None
        assert row[0] == "failed", f"Expected 'failed', got '{row[0]}'"


def test_auth_and_business_picker(client):
    # Test valid login with seeded owner
    login_resp = client.post("/auth/login", json={"email": "owner@demo.com", "password": "password123"})
    assert login_resp.status_code == 200
    data = login_resp.json()
    assert "token" in data
    token = data["token"]

    # Test /auth/me
    headers = {"Authorization": f"Bearer {token}"}
    me_resp = client.get("/auth/me", headers=headers)
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["email"] == "owner@demo.com"
    assert "demo-stationery-1" in me_data["businesses"]

    # Test /businesses
    biz_resp = client.get("/businesses", headers=headers)
    assert biz_resp.status_code == 200
    biz_data = biz_resp.json()
    assert len(biz_data) >= 3

    # Test restricted owner
    r_login = client.post("/auth/login", json={"email": "restricted@demo.com", "password": "password123"})
    assert r_login.status_code == 200
    r_token = r_login.json()["token"]
    r_headers = {"Authorization": f"Bearer {r_token}"}
    r_biz_resp = client.get("/businesses", headers=r_headers)
    assert r_biz_resp.status_code == 200
    assert len(r_biz_resp.json()) == 1
    assert r_biz_resp.json()[0]["business_id"] == "demo-stationery-1"

    # Test invalid login
    bad_login = client.post("/auth/login", json={"email": "owner@demo.com", "password": "wrong"})
    assert bad_login.status_code == 401


def test_bot_link_issue_and_consume(client):
    # Login as owner
    login_resp = client.post("/auth/login", json={"email": "owner@demo.com", "password": "password123"})
    token = login_resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Issue link for demo-supermarket-1
    link_resp = client.post("/businesses/demo-supermarket-1/bot-link", headers=headers)
    assert link_resp.status_code == 200
    link_data = link_resp.json()
    bot_token = link_data["token"]
    assert "start=" in link_data["deep_link_url"]

    # Consume token for a test chat
    test_chat_id = 999111222
    success, biz_id, msg = consume_token(bot_token, test_chat_id)
    assert success is True
    assert biz_id == "demo-supermarket-1"

    # Attempt to consume AGAIN (reused token check)
    success2, biz_id2, msg2 = consume_token(bot_token, test_chat_id)
    assert success2 is False
    assert "already been used" in msg2

    # Check sessions table
    with get_conn() as conn:
        s_row = conn.execute(
            "SELECT active_business_id FROM sessions WHERE customer_phone = %s",
            (str(test_chat_id),),
        ).fetchone()
        assert s_row is not None
        assert s_row[0] == "demo-supermarket-1"


def test_webhook_unique_input_id_and_duplicate_safety(client):
    test_update_id = 88776655
    bot_id = settings.telegram_bot_token.split(":")[0]
    expected_input_id = f"tg:{bot_id}:{test_update_id}"
    chat_id = 777666555

    payload = {
        "update_id": test_update_id,
        "message": {
            "message_id": 101,
            "chat": {"id": chat_id},
            "text": "Hello bot"
        }
    }
    headers = {
        "X-Telegram-Bot-Api-Secret-Token": settings.telegram_webhook_secret
    }

    # 1. Send first time
    resp = client.post("/webhook/telegram", json=payload, headers=headers)
    assert resp.status_code == 200

    # Verify stored row has globally unique input_id and separate columns
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT input_id, telegram_chat_id, telegram_update_id, telegram_message_id, business_id
            FROM inbox
            WHERE input_id = %s
            """,
            (expected_input_id,),
        ).fetchone()
        assert row is not None
        assert row[0] == expected_input_id
        assert row[1] == chat_id
        assert row[2] == test_update_id
        assert row[3] == 101
        persisted_biz = row[4]

    # 2. Send duplicate update_id with DIFFERENT payload context (e.g. spoofed tenant or text)
    spoofed_payload = {
        "update_id": test_update_id,
        "message": {
            "message_id": 999,
            "chat": {"id": 111222333},
            "text": "Spoofed message"
        }
    }
    resp2 = client.post("/webhook/telegram", json=spoofed_payload, headers=headers)
    assert resp2.status_code == 200

    # Ensure row was NOT mutated by duplicate request
    with get_conn() as conn:
        row_after = conn.execute(
            """
            SELECT input_id, telegram_chat_id, business_id
            FROM inbox
            WHERE input_id = %s
            """,
            (expected_input_id,),
        ).fetchone()
        assert row_after[1] == chat_id  # unchanged, not 111222333
        assert row_after[2] == persisted_biz


def test_dispatcher_attention_and_retry():
    test_input_id = f"tg:test:attention_{uuid.uuid4().hex[:8]}"
    session_id = str(uuid.uuid4())
    unique_phone = f"phone_{uuid.uuid4().hex[:8]}"

    with get_conn() as conn:
        with conn.transaction():
            conn.execute(
                """
                INSERT INTO sessions (session_id, customer_phone, destination, active_business_id)
                VALUES (%s, %s, 'telegram_bot', 'demo-stationery-1')
                """,
                (session_id, unique_phone),
            )
            conn.execute(
                """
                INSERT INTO inbox (input_id, source, session_id, business_id, body, status, attempts)
                VALUES (%s, 'telegram', %s, 'demo-stationery-1', '{"text": "fail me"}'::jsonb, 'received', 2)
                """,
                (test_input_id, session_id),
            )

    # Force error in run_terminal_action to exhaust retries
    with patch("app.dispatcher.run_terminal_action", side_effect=RuntimeError("Simulated failure")):
        import asyncio
        asyncio.run(_process_one(test_input_id, session_id, "demo-stationery-1"))

    # Assert row is marked 'attention'
    with get_conn() as conn:
        row = conn.execute(
            "SELECT status, last_error FROM inbox WHERE input_id = %s",
            (test_input_id,),
        ).fetchone()
        assert row[0] == "attention"
        assert "Simulated failure" in row[1]

        # Verify event was written
        evt = conn.execute(
            "SELECT kind FROM events WHERE input_id = %s",
            (test_input_id,),
        ).fetchone()
        assert evt is not None
        assert evt[0] == "inbox_attention"

    # Now test owner retry
    retried = retry_attention_row(test_input_id)
    assert retried is True
    with get_conn() as conn:
        row_retried = conn.execute(
            "SELECT status, attempts FROM inbox WHERE input_id = %s",
            (test_input_id,),
        ).fetchone()
        assert row_retried[0] == "received"
        assert row_retried[1] == 0


def test_n8n_notify_failure_resilience():
    # Calling notify_hold on non-existent order or down endpoint never raises
    result = notify_hold("00000000-0000-0000-0000-000000000000", "demo-stationery-1")
    # Returns boolean, never throws
    assert isinstance(result, bool)
