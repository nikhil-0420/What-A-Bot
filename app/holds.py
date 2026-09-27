"""
Held-order flow and n8n notification (Section G).

Threshold crossed on confirm:
    draft -> held (no stock deducted, no invoice)
    persist customer reply + owner-visible held order
    [transaction commits]
    AFTER commit: best-effort notification to ONE configured n8n webhook

Notification failure must NEVER change the order outcome or block the
customer reply -- the owner queue is the authoritative review mechanism
regardless of whether the ping arrives. The notification contains an
order reference and a link to the owner page -- never approval
credentials. n8n never authorizes anything and never receives a callback.
"""
import asyncio
import json
import logging
import uuid
import httpx

from app.config import settings
from app.db import get_conn
import app.db as db_module
from app.transactions import run_terminal_action, decrement_stock

log = logging.getLogger(__name__)

# Shared httpx client — reuses connections across notifications
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    """Lazy singleton with connection-pool limits. Re-created if closed."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=3.0,
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
        )
    return _http_client


def draft_to_held(order_id: str, business_id: str, session_id: str, input_id: str, conn=None) -> dict:
    """Runs inside the same terminal-action transaction as an ordinary
    confirm -- see transactions.run_terminal_action. Sets status='held'
    instead of 'confirmed', skips stock decrement and invoice creation."""

    def _business_action(tx_conn):
        row = tx_conn.execute(
            """
            UPDATE orders SET status = 'held'
            WHERE order_id = %s AND business_id = %s AND session_id = %s AND status = 'draft'
            RETURNING order_id, total_paise
            """,
            (order_id, business_id, session_id),
        ).fetchone()

        if row is None:
            # Check existing order state
            existing = tx_conn.execute(
                "SELECT status, total_paise FROM orders WHERE order_id = %s",
                (order_id,),
            ).fetchone()
            if existing and existing[0] == "held":
                return {"status": "held", "order_id": order_id, "total_paise": existing[1], "replayed": True}
            raise ValueError(f"Order {order_id} not eligible for hold transition (not draft)")

        total_paise = row[1]
        return {
            "status": "held",
            "order_id": order_id,
            "business_id": business_id,
            "session_id": session_id,
            "total_paise": total_paise,
        }

    reply_payload = {
        "text": (
            f"Your order (ID: {order_id}) exceeds the standard review threshold "
            f"and has been held for store owner review. You will be notified once reviewed."
        ),
        "order_id": order_id,
        "status": "held",
    }

    result = run_terminal_action(
        input_id=input_id,
        session_id=session_id,
        business_id=business_id,
        kind="hold",
        business_action=_business_action,
        reply_payload=reply_payload,
        conn=conn,
    )

    # Best-effort notification AFTER commit
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(notify_n8n_hold(order_id, business_id))
    except RuntimeError:
        log.debug("No running event loop; skipping asynchronous n8n notification")

    return result


async def notify_n8n_hold(order_id: str, business_id: str) -> None:
    """
    Called AFTER the held-order transaction commits -- never inside it.
    Authenticated with N8N_SHARED_SECRET, short timeout. Record
    success/failure in `events`. Swallow failures -- see docstring above.
    """
    webhook_url = getattr(settings, "n8n_webhook_url", "")
    if not webhook_url:
        log.info("n8n notification skipped: N8N_WEBHOOK_URL not configured")
        return

    secret = getattr(settings, "n8n_shared_secret", "")
    payload = {
        "event": "order_held",
        "order_id": order_id,
        "business_id": business_id,
        "owner_review_url": f"/businesses/{business_id}/holds",
    }

    status = "failed"
    error_msg = None

    try:
        client = _get_http_client()
        resp = await client.post(
            webhook_url,
            json=payload,
            headers={"X-N8N-Shared-Secret": secret},
        )
        if resp.status_code < 400:
            status = "success"
            log.info("n8n hold notification sent for order %s (status %d)", order_id, resp.status_code)
        else:
            error_msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
            log.warning("n8n hold notification returned %s", error_msg)
    except Exception as e:
        error_msg = str(e)
        log.warning("n8n hold notification network failure for order %s: %s", order_id, e)

    # Record in events table (swallow failure)
    try:
        if getattr(db_module, "pool", None) is not None:
            with get_conn() as conn:
                with conn.transaction():
                    conn.execute(
                        """
                        INSERT INTO events (kind, data)
                        VALUES ('n8n_notification', %s)
                        """,
                        (json.dumps({
                            "order_id": order_id,
                            "business_id": business_id,
                            "status": status,
                            "error": error_msg,
                        }),),
                    )
    except Exception as db_err:
        log.debug("Could not record n8n event in DB: %s", db_err)


def owner_resolve_hold(order_id: str, business_id: str, approve: bool, conn=None) -> dict:
    """
    Owner approve/reject on the protected page. Same CAS + transaction
    pattern as customer confirmation, expected_status='held'. Repeat
    actions return the stored/current terminal state (idempotent).
    """
    def _execute(tx_conn):
        # 1. Fetch current order
        row = tx_conn.execute(
            """
            SELECT order_id, session_id, business_id, status, items, total_paise
            FROM orders
            WHERE order_id = %s AND business_id = %s
            """,
            (order_id, business_id),
        ).fetchone()

        if row is None:
            raise ValueError(f"Order {order_id} not found for business {business_id}")

        curr_order_id, session_id, b_id, status, items_raw, total_paise = row
        items = json.loads(items_raw) if isinstance(items_raw, str) else items_raw

        # 2. Idempotency: repeat calls return current terminal state
        if status == "confirmed":
            return {
                "status": "already_resolved",
                "order_id": str(order_id),
                "decision": "approved",
                "order_status": "confirmed",
            }
        if status == "cancelled":
            return {
                "status": "already_resolved",
                "order_id": str(order_id),
                "decision": "rejected",
                "order_status": "cancelled",
            }
        if status != "held":
            raise ValueError(f"Order {order_id} is in invalid status '{status}' for hold resolution")

        if approve:
            # CAS update: held -> confirmed
            cas_row = tx_conn.execute(
                """
                UPDATE orders SET status = 'confirmed'
                WHERE order_id = %s AND business_id = %s AND status = 'held'
                RETURNING order_id
                """,
                (order_id, business_id),
            ).fetchone()

            if cas_row is None:
                # Concurrent update won the race
                return {
                    "status": "already_resolved",
                    "order_id": str(order_id),
                    "decision": "approved",
                    "order_status": "confirmed",
                }

            # Decrement stock in sorted SKU order
            sorted_items = sorted(items, key=lambda x: x["sku"])
            for it in sorted_items:
                rem = decrement_stock(
                    tx_conn,
                    business_id,
                    it["sku"],
                    it["qty"],
                    it["unit_price_paise"],
                )
                if rem is None:
                    # Rollback whole transaction on partial failure
                    raise ValueError(f"Insufficient stock or price mismatch for SKU {it['sku']} during hold approval")

            # Create invoice
            invoice_id = str(uuid.uuid4())
            inv_payload = {
                "order_id": str(order_id),
                "business_id": business_id,
                "session_id": str(session_id),
                "total_paise": total_paise,
                "items": items,
            }
            tx_conn.execute(
                """
                INSERT INTO invoices (order_id, invoice_id, payload)
                VALUES (%s, %s, %s)
                """,
                (order_id, invoice_id, json.dumps(inv_payload)),
            )

            # Record event
            tx_conn.execute(
                """
                INSERT INTO events (kind, data)
                VALUES ('owner_hold_approved', %s)
                """,
                (json.dumps({"order_id": str(order_id), "business_id": business_id}),),
            )

            return {
                "status": "confirmed",
                "order_id": str(order_id),
                "invoice_id": invoice_id,
                "decision": "approved",
            }
        else:
            # Reject: held -> cancelled
            cas_row = tx_conn.execute(
                """
                UPDATE orders SET status = 'cancelled'
                WHERE order_id = %s AND business_id = %s AND status = 'held'
                RETURNING order_id
                """,
                (order_id, business_id),
            ).fetchone()

            if cas_row is None:
                return {
                    "status": "already_resolved",
                    "order_id": str(order_id),
                    "decision": "rejected",
                    "order_status": "cancelled",
                }

            # Record event
            tx_conn.execute(
                """
                INSERT INTO events (kind, data)
                VALUES ('owner_hold_rejected', %s)
                """,
                (json.dumps({"order_id": str(order_id), "business_id": business_id}),),
            )

            return {
                "status": "cancelled",
                "order_id": str(order_id),
                "decision": "rejected",
            }

    if conn is not None:
        with conn.transaction():
            return _execute(conn)
    else:
        with get_conn() as c:
            with c.transaction():
                return _execute(c)
