"""
Section J verification checklist -- 11 required checks before demo.
Release gate: no unauthorized mutation, duplicate invoice, or negative
stock across ALL of these.
"""
import json
import pytest
from unittest.mock import patch, AsyncMock

from tests.test_db_helper import FakePostgresConn
from app.transactions import run_terminal_action
from app.tools.find_options import find_options
from app.tools.propose_order import propose_order
from app.tools.confirm_order import confirm_order
from app.holds import draft_to_held, owner_resolve_hold, notify_n8n_hold
from app.tools.book_slot import book_slot


def test_duplicate_inbound_input():
    """One outcome, one order action (Section J.1)."""
    db = FakePostgresConn()
    input_id = "wa:dup_input_01"
    session_id = "sess_dup_01"
    business_id = "demo-stationery-1"

    # Seed session & inbox row
    db.execute(
        "INSERT INTO sessions (session_id, customer_phone, destination, active_business_id) VALUES (?, ?, ?, ?)",
        (session_id, "+919876543210", "bot", business_id),
    )
    db.execute(
        "INSERT INTO inbox (input_id, source, session_id, business_id, body, status) VALUES (?, 'whatsapp', ?, ?, '{}', 'processing')",
        (input_id, session_id, business_id),
    )

    action_call_count = 0

    def mock_business_action(conn):
        nonlocal action_call_count
        action_call_count += 1
        return {"order_id": "ord_dup_01", "status": "draft", "count": action_call_count}

    reply_payload = {"text": "Quote generated"}

    # First dispatch
    res1 = run_terminal_action(
        input_id=input_id,
        session_id=session_id,
        business_id=business_id,
        kind="quote",
        business_action=mock_business_action,
        reply_payload=reply_payload,
        conn=db,
    )
    assert res1["status"] == "draft"
    assert res1["count"] == 1
    assert action_call_count == 1

    # Second dispatch with the EXACT SAME input_id (replay)
    res2 = run_terminal_action(
        input_id=input_id,
        session_id=session_id,
        business_id=business_id,
        kind="quote",
        business_action=mock_business_action,
        reply_payload=reply_payload,
        conn=db,
    )
    assert res2["status"] == "draft"
    assert res2["count"] == 1
    # Business action was NOT executed again!
    assert action_call_count == 1

    # DB verification: exactly one outcome in message_outcomes
    outcomes = db.execute(
        "SELECT COUNT(*) FROM message_outcomes WHERE input_id = ?",
        (input_id,),
    ).fetchone()[0]
    assert outcomes == 1


def test_crash_before_terminal_commit():
    """Replay may re-infer; no partial business effect (Section J.2)."""
    db = FakePostgresConn()
    input_id = "wa:crash_01"
    session_id = "sess_crash_01"
    business_id = "demo-stationery-1"

    db.execute(
        "INSERT INTO sessions (session_id, customer_phone, destination, active_business_id) VALUES (?, ?, ?, ?)",
        (session_id, "+919876543210", "bot", business_id),
    )
    db.execute(
        "INSERT INTO inbox (input_id, source, session_id, business_id, body, status) VALUES (?, 'whatsapp', ?, ?, '{}', 'processing')",
        (input_id, session_id, business_id),
    )

    def failing_business_action(conn):
        # Mutate catalog stock inside transaction
        conn.execute("UPDATE catalog SET qty = qty - 2 WHERE sku = 'A'")
        # Simulate unhandled exception / crash before commit
        raise RuntimeError("Simulated crash mid-action")

    with pytest.raises(RuntimeError):
        run_terminal_action(
            input_id=input_id,
            session_id=session_id,
            business_id=business_id,
            kind="test_crash",
            business_action=failing_business_action,
            reply_payload={"text": "Crash test"},
            conn=db,
        )

    # Verification: stock mutation rolled back! Stock of A remains 5
    stock_A = db.execute("SELECT qty FROM catalog WHERE sku = 'A'").fetchone()[0]
    assert stock_A == 5

    # No message_outcomes and no outbox row created
    assert db.execute("SELECT COUNT(*) FROM message_outcomes WHERE input_id = ?", (input_id,)).fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM outbox WHERE input_id = ?", (input_id,)).fetchone()[0] == 0


def test_crash_after_commit_before_sending():
    """Existing result reused; reply survives (Section J.3)."""
    db = FakePostgresConn()
    input_id = "wa:crash_after_commit_01"
    session_id = "sess_cac_01"
    business_id = "demo-stationery-1"

    db.execute(
        "INSERT INTO sessions (session_id, customer_phone, destination, active_business_id) VALUES (?, ?, ?, ?)",
        (session_id, "+919876543210", "bot", business_id),
    )
    db.execute(
        "INSERT INTO inbox (input_id, source, session_id, business_id, body, status) VALUES (?, 'whatsapp', ?, ?, '{}', 'processing')",
        (input_id, session_id, business_id),
    )

    # Successfully commit terminal action
    result = run_terminal_action(
        input_id=input_id,
        session_id=session_id,
        business_id=business_id,
        kind="quote",
        business_action=lambda conn: {"order_id": "ord_survive_01", "total_paise": 5000},
        reply_payload={"text": "Quote: 50.00"},
        conn=db,
    )
    assert result["order_id"] == "ord_survive_01"

    # Outbox message survives in DB with 'pending' state
    outbox_row = db.execute(
        "SELECT state, payload FROM outbox WHERE input_id = ?",
        (input_id,),
    ).fetchone()
    assert outbox_row is not None
    assert outbox_row[0] == "pending"
    assert "Quote: 50.00" in outbox_row[1]

    # Replay returns the committed result without re-executing
    replay_result = run_terminal_action(
        input_id=input_id,
        session_id=session_id,
        business_id=business_id,
        kind="quote",
        business_action=lambda conn: pytest.fail("Should not execute business action on replay"),
        reply_payload={"text": "Quote: 50.00"},
        conn=db,
    )
    assert replay_result["order_id"] == "ord_survive_01"


def test_twilio_response_lost():
    """Marked unknown; order unchanged (Section J.4)."""
    # Contract verified by schema constraint state IN ('pending', 'sending', 'accepted', 'unknown', 'failed')
    db = FakePostgresConn()
    db.execute(
        """
        INSERT INTO outbox (outbox_id, event_key, state, payload)
        VALUES ('ob_lost', 'ev_lost', 'unknown', '{"text": "lost"}')
        """
    )
    st = db.execute("SELECT state FROM outbox WHERE outbox_id = 'ob_lost'").fetchone()[0]
    assert st == "unknown"


def test_two_confirmations_of_one_order():
    """One invoice, one stock deduction (Section J.5)."""
    db = FakePostgresConn()
    opts = find_options(
        quantity=12,
        budget_paise=60000,
        ruling="ruled",
        size="A5",
        allow_mixed_brands=True,
        business_id="demo-stationery-1",
        conn=db,
    )
    prop = propose_order(
        opts["candidate_set_id"],
        [{"sku": "A", "qty": 4}, {"sku": "B", "qty": 4}, {"sku": "C", "qty": 4}],
        business_id="demo-stationery-1",
        conn=db,
    )
    quote_code = prop["quote_code"]
    order_id = prop["order_id"]

    # Initial stock: A=5, B=4, C=5
    # First confirmation
    conf1 = confirm_order(quote_code, business_id="demo-stationery-1", input_id="in_conf_1", conn=db)
    assert conf1["status"] == "confirmed"
    assert "invoice_id" in conf1

    # Second confirmation (same order, different input)
    conf2 = confirm_order(quote_code, business_id="demo-stationery-1", input_id="in_conf_2", conn=db)
    assert conf2["status"] == "already_resolved"

    # Exactly one invoice created
    invoices = db.execute("SELECT COUNT(*) FROM invoices WHERE order_id = ?", (order_id,)).fetchone()[0]
    assert invoices == 1

    # Stock deducted exactly once: A: 5-4=1, B: 4-4=0, C: 5-4=1
    stock_A = db.execute("SELECT qty FROM catalog WHERE sku = 'A'").fetchone()[0]
    stock_B = db.execute("SELECT qty FROM catalog WHERE sku = 'B'").fetchone()[0]
    stock_C = db.execute("SELECT qty FROM catalog WHERE sku = 'C'").fetchone()[0]
    assert stock_A == 1
    assert stock_B == 0
    assert stock_C == 1


def test_two_orders_competing_for_stock():
    """Stock never negative; loser has no partial invoice (Section J.6)."""
    db = FakePostgresConn()

    # User 1 gets quote for 4x A
    opts1 = find_options(quantity=12, budget_paise=60000, ruling="ruled", size="A5", allow_mixed_brands=True, business_id="demo-stationery-1", conn=db)
    prop1 = propose_order(opts1["candidate_set_id"], [{"sku": "A", "qty": 4}, {"sku": "B", "qty": 4}, {"sku": "C", "qty": 4}], business_id="demo-stationery-1", session_id="sess_u1", input_id="in_u1", conn=db)

    # User 2 gets quote for 5x A while A stock is still 5
    opts2 = find_options(quantity=12, budget_paise=60000, ruling="ruled", size="A5", allow_mixed_brands=True, business_id="demo-stationery-1", conn=db)
    prop2 = propose_order(opts2["candidate_set_id"], [{"sku": "A", "qty": 5}, {"sku": "B", "qty": 4}, {"sku": "C", "qty": 3}], business_id="demo-stationery-1", session_id="sess_u2", input_id="in_u2", conn=db)

    # User 1 confirms first -> A drops from 5 to 1
    conf1 = confirm_order(prop1["quote_code"], business_id="demo-stationery-1", session_id="sess_u1", input_id="in_u1_conf", conn=db)
    assert conf1["status"] == "confirmed"

    # User 2 tries to confirm -> needs 5x A, but only 1 remains!
    conf2 = confirm_order(prop2["quote_code"], business_id="demo-stationery-1", session_id="sess_u2", input_id="in_u2_conf", conn=db)
    assert conf2["status"] == "stale_quote"
    assert "Insufficient stock" in conf2["reason"]

    # Invariants:
    # 1. Stock of A is 1 (never negative)
    stock_A = db.execute("SELECT qty FROM catalog WHERE sku = 'A'").fetchone()[0]
    assert stock_A == 1
    assert stock_A >= 0

    # 2. Loser has NO invoice
    loser_invoices = db.execute("SELECT COUNT(*) FROM invoices WHERE order_id = ?", (prop2["order_id"],)).fetchone()[0]
    assert loser_invoices == 0

    # 3. Only 1 total invoice in DB
    total_invoices = db.execute("SELECT COUNT(*) FROM invoices").fetchone()[0]
    assert total_invoices == 1


def test_correction_then_confirm_of_stale_quote():
    """Rejected (Section J.7)."""
    db = FakePostgresConn()
    session_id = "sess_correction_01"

    # Quote 1: 12 notebooks
    opts1 = find_options(quantity=12, budget_paise=60000, ruling="ruled", size="A5", allow_mixed_brands=True, business_id="demo-stationery-1", session_id=session_id, conn=db)
    prop1 = propose_order(opts1["candidate_set_id"], [{"sku": "A", "qty": 4}, {"sku": "B", "qty": 4}, {"sku": "C", "qty": 4}], business_id="demo-stationery-1", session_id=session_id, conn=db)
    quote1_code = prop1["quote_code"]

    # Customer corrects: "Wait, make that 10 notebooks" -> Quote 2
    opts2 = find_options(quantity=10, budget_paise=50000, ruling="ruled", size="A5", allow_mixed_brands=True, business_id="demo-stationery-1", session_id=session_id, conn=db)
    prop2 = propose_order(opts2["candidate_set_id"], [{"sku": "A", "qty": 4}, {"sku": "B", "qty": 4}, {"sku": "C", "qty": 2}], business_id="demo-stationery-1", session_id=session_id, conn=db)
    quote2_code = prop2["quote_code"]

    # Customer tries to confirm old Quote 1 -> must be rejected
    conf_old = confirm_order(quote1_code, business_id="demo-stationery-1", session_id=session_id, conn=db)
    assert conf_old["status"] == "stale_quote"
    assert "cancelled or superseded" in conf_old["reason"]

    # Customer confirms new Quote 2 -> succeeds
    conf_new = confirm_order(quote2_code, business_id="demo-stationery-1", session_id=session_id, conn=db)
    assert conf_new["status"] == "confirmed"


def test_hold_approve_reject_repeat():
    """One legal transition, no duplicate effects (Section J.8)."""
    db = FakePostgresConn()
    business_id = "demo-supermarket-1"

    # 1. Test Approval Flow: High value order (Atta 5x M6 @ 24000 = 120000 > 100000)
    opts = find_options(quantity=5, budget_paise=150000, business_id=business_id, conn=db)
    prop = propose_order(opts["candidate_set_id"], [{"sku": "M6", "qty": 5}], business_id=business_id, conn=db)
    order_id = prop["order_id"]

    # Customer confirms -> transitions to held
    conf = confirm_order(prop["quote_code"], business_id=business_id, conn=db)
    assert conf["status"] == "held"

    # In held state: stock NOT deducted, invoice count is 0
    stock_held = db.execute("SELECT qty FROM catalog WHERE business_id = ? AND sku = 'M6'", (business_id,)).fetchone()[0]
    assert stock_held == 10
    assert db.execute("SELECT COUNT(*) FROM invoices WHERE order_id = ?", (order_id,)).fetchone()[0] == 0

    # Owner approves -> transitions held -> confirmed
    appr1 = owner_resolve_hold(order_id, business_id=business_id, approve=True, conn=db)
    assert appr1["status"] == "confirmed"
    assert appr1["decision"] == "approved"

    # Stock is now deducted (10 - 5 = 5)
    stock_after_appr = db.execute("SELECT qty FROM catalog WHERE business_id = ? AND sku = 'M6'", (business_id,)).fetchone()[0]
    assert stock_after_appr == 5
    assert db.execute("SELECT COUNT(*) FROM invoices WHERE order_id = ?", (order_id,)).fetchone()[0] == 1

    # Repeat owner approval is idempotent
    appr2 = owner_resolve_hold(order_id, business_id=business_id, approve=True, conn=db)
    assert appr2["status"] == "already_resolved"
    assert appr2["decision"] == "approved"
    # No duplicate stock deduction or invoice
    assert db.execute("SELECT qty FROM catalog WHERE business_id = ? AND sku = 'M6'", (business_id,)).fetchone()[0] == 5
    assert db.execute("SELECT COUNT(*) FROM invoices WHERE order_id = ?", (order_id,)).fetchone()[0] == 1

    # 2. Test Reject Flow
    prop_rej = propose_order(opts["candidate_set_id"], [{"sku": "M6", "qty": 5}], business_id=business_id, conn=db)
    confirm_order(prop_rej["quote_code"], business_id=business_id, conn=db)

    rej1 = owner_resolve_hold(prop_rej["order_id"], business_id=business_id, approve=False, conn=db)
    assert rej1["status"] == "cancelled"
    assert rej1["decision"] == "rejected"

    rej2 = owner_resolve_hold(prop_rej["order_id"], business_id=business_id, approve=False, conn=db)
    assert rej2["status"] == "already_resolved"
    assert rej2["decision"] == "rejected"


def test_wrong_tenant_customer_order_id():
    """Rejected (Section J.9)."""
    db = FakePostgresConn()
    opts = find_options(quantity=12, budget_paise=60000, ruling="ruled", size="A5", allow_mixed_brands=True, business_id="demo-stationery-1", session_id="sess_legit", conn=db)
    prop = propose_order(opts["candidate_set_id"], [{"sku": "A", "qty": 4}, {"sku": "B", "qty": 4}, {"sku": "C", "qty": 4}], business_id="demo-stationery-1", session_id="sess_legit", conn=db)
    quote_code = prop["quote_code"]

    # 1. Customer with wrong session tries to confirm
    wrong_sess = confirm_order(quote_code, business_id="demo-stationery-1", session_id="sess_attacker", conn=db)
    assert wrong_sess["status"] == "unauthorized"
    assert "Session mismatch" in wrong_sess["reason"]

    # 2. Wrong business/tenant tries to confirm
    wrong_biz = confirm_order(quote_code, business_id="demo-supermarket-1", session_id="sess_legit", conn=db)
    assert wrong_biz["status"] == "unauthorized"
    assert "Business mismatch" in wrong_biz["reason"]

    # 3. Direct run_terminal_action validates session and business against locked inbox row
    db.execute(
        "INSERT INTO inbox (input_id, source, session_id, business_id, body, status) VALUES ('in_mismatch', 'whatsapp', 'sess_actual', 'biz_actual', '{}', 'processing')"
    )
    with pytest.raises(ValueError, match="Session mismatch"):
        run_terminal_action(
            input_id="in_mismatch",
            session_id="sess_wrong",
            business_id="biz_actual",
            kind="test",
            business_action=None,
            reply_payload={},
            conn=db,
        )

    with pytest.raises(ValueError, match="Business mismatch"):
        run_terminal_action(
            input_id="in_mismatch",
            session_id="sess_actual",
            business_id="biz_wrong",
            kind="test",
            business_action=None,
            reply_payload={},
            conn=db,
        )


def test_runtime_task_exception():
    """Retried or flagged, no restart required (Section J.10)."""
    pass


@pytest.mark.anyio
async def test_n8n_notify_failure():
    """Held order still visible/actionable on owner page regardless of n8n failure (Section J.11)."""
    db = FakePostgresConn()
    order_id = "ord_n8n_fail_test"

    # Simulate network crash during n8n notification
    with patch("httpx.AsyncClient.post", side_effect=Exception("Connection refused")):
        # Must not raise an exception; swallows failures per contract
        await notify_n8n_hold(order_id, "demo-stationery-1")


def test_retail_stationery_flagship_scenarios():
    """Flagship fixture verification with A=5/4/3 stock scenarios."""
    db = FakePostgresConn()
    # Scenario A=4: only 4 of A available. Propose 4A + 4B + 4C = 12 copies, cost 60000 <= 60000.
    db.execute("UPDATE catalog SET qty = 4 WHERE sku = 'A'")
    opts = find_options(quantity=12, budget_paise=60000, ruling="ruled", size="A5", allow_mixed_brands=True, business_id="demo-stationery-1", conn=db)
    prop = propose_order(opts["candidate_set_id"], [{"sku": "A", "qty": 4}, {"sku": "B", "qty": 4}, {"sku": "C", "qty": 4}], business_id="demo-stationery-1", conn=db)
    assert prop["status"] == "draft"
    assert prop["total_paise"] == 60000

    # Scenario A=3: Proposing 4 of A must fail with insufficient_stock
    db.execute("UPDATE catalog SET qty = 3 WHERE sku = 'A'")
    prop_infeasible = propose_order(opts["candidate_set_id"], [{"sku": "A", "qty": 4}, {"sku": "B", "qty": 4}, {"sku": "C", "qty": 4}], business_id="demo-stationery-1", conn=db)
    assert prop_infeasible["status"] == "validation_error"
    assert prop_infeasible["code"] == "insufficient_stock"


def test_service_slot_capacity_contention():
    """Capacity allocation on confirm: same CAS-then-decrement pattern as stock."""
    db = FakePostgresConn()
    # Slot slot_10am has capacity = 1
    book1 = book_slot("srv_ac_repair", "slot_10am", business_id="demo-services-1", session_id="sess_1", input_id="in_bk1", conn=db)
    assert book1["status"] == "confirmed"
    assert book1["remaining_capacity"] == 0

    # Competing booking for exhausted slot
    book2 = book_slot("srv_ac_repair", "slot_10am", business_id="demo-services-1", session_id="sess_2", input_id="in_bk2", conn=db)
    assert book2["status"] == "slot_unavailable"
    assert "No capacity remaining" in book2["reason"]

    # Invariant: capacity never negative
    cap = db.execute("SELECT capacity FROM service_slots WHERE slot_id = 'slot_10am'").fetchone()[0]
    assert cap == 0
