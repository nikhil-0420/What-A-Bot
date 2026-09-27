"""Section E tool contract -- signature is fixed, implement the body."""
import json
import logging
import uuid
from datetime import datetime, timezone

from app.db import get_conn
import app.db as db_module
from app.transactions import run_terminal_action, decrement_stock
from app.holds import draft_to_held
from app.tools.propose_order import _ensure_inbox_session

log = logging.getLogger(__name__)


class StaleQuoteError(Exception):
    """Raised when stock or price is no longer valid, rolling back confirmation."""
    pass


class AlreadyResolvedError(Exception):
    """Raised when the order was already confirmed or resolved."""
    pass


def _get_business_review_threshold(business_id: str, conn=None) -> int:
    """Look up review_above_paise threshold for the business."""
    default_thresh = 100_000
    try:
        if conn is not None:
            row = conn.execute(
                "SELECT review_above_paise FROM businesses WHERE business_id = %s",
                (business_id,),
            ).fetchone()
            if row:
                return row[0]
        elif getattr(db_module, "pool", None) is not None:
            with get_conn() as c:
                row = c.execute(
                    "SELECT review_above_paise FROM businesses WHERE business_id = %s",
                    (business_id,),
                ).fetchone()
                if row:
                    return row[0]
    except Exception as e:
        log.debug("Could not fetch business review threshold: %s", e)
    return default_thresh


def confirm_order(
    order_id: str,
    *,
    input_id: str | None = None,
    session_id: str | None = None,
    business_id: str | None = None,
    conn=None,
) -> dict:
    """
    Requires an explicit customer command (e.g. "CONFIRM Q7K2"). Backend
    resolves the quote and injects authorization -- never model-invented.
    Checks session, tenant, expiry, status, stock, current price. Returns
    the existing result if already resolved (idempotent). Can be routed
    deterministically -- no unnecessary model call just to look more
    agentic.

    Returns one of: Confirmed | Held | StaleQuote | AlreadyResolved
    """
    # 1. Resolve order from DB
    def _fetch_order(c):
        return c.execute(
            """
            SELECT order_id, quote_code, session_id, business_id, status, items, total_paise, expires_at
            FROM orders
            WHERE (order_id::text = %s OR quote_code = %s)
            """,
            (str(order_id), str(order_id)),
        ).fetchone()

    row = None
    if conn is not None:
        row = _fetch_order(conn)
    elif getattr(db_module, "pool", None) is not None:
        try:
            with get_conn() as c:
                row = _fetch_order(c)
        except Exception as e:
            log.warning("Could not fetch order %s: %s", order_id, e)

    if row is None:
        return {
            "status": "stale_quote",
            "reason": "Order not found",
            "order_id": str(order_id),
        }

    actual_order_id, quote_code, ord_session_id, ord_business_id, status, items_raw, total_paise, expires_at = row
    actual_order_id = str(actual_order_id)
    ord_session_id = str(ord_session_id)
    items = json.loads(items_raw) if isinstance(items_raw, str) else items_raw

    # 2. Check authorization: session and business must match if provided
    if session_id is not None and str(session_id) != ord_session_id:
        return {
            "status": "unauthorized",
            "reason": f"Session mismatch: order belongs to {ord_session_id}, supplied {session_id}",
            "order_id": actual_order_id,
        }
    if business_id is not None and str(business_id) != ord_business_id:
        return {
            "status": "unauthorized",
            "reason": f"Business mismatch: order belongs to {ord_business_id}, supplied {business_id}",
            "order_id": actual_order_id,
        }

    # 3. Check current order status
    if status == "confirmed":
        return {
            "status": "already_resolved",
            "order_id": actual_order_id,
            "order_status": "confirmed",
        }
    if status == "cancelled":
        return {
            "status": "stale_quote",
            "reason": "Quote has been cancelled or superseded",
            "order_id": actual_order_id,
        }
    if status == "held":
        return {
            "status": "already_resolved",
            "order_id": actual_order_id,
            "order_status": "held",
        }

    # 4. Check expiry
    if expires_at is not None:
        if isinstance(expires_at, str):
            try:
                expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            except Exception:
                pass
        if isinstance(expires_at, datetime):
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at < datetime.now(timezone.utc):
                return {
                    "status": "stale_quote",
                    "reason": "Quote has expired",
                    "order_id": actual_order_id,
                }

    effective_input_id = input_id or f"in_{uuid.uuid4().hex[:12]}"

    # 5. Ensure inbox + fetch hold threshold in one connection checkout
    if conn is not None:
        _ensure_inbox_session(conn, effective_input_id, ord_session_id, ord_business_id)
        threshold = _get_business_review_threshold(ord_business_id, conn=conn)
    elif getattr(db_module, "pool", None) is not None:
        threshold = _get_business_review_threshold(ord_business_id)  # default fallback
        try:
            with get_conn() as c:
                with c.transaction():
                    _ensure_inbox_session(c, effective_input_id, ord_session_id, ord_business_id)
                threshold = _get_business_review_threshold(ord_business_id, conn=c)
        except Exception:
            pass
    else:
        threshold = _get_business_review_threshold(ord_business_id)
    if total_paise > threshold:
        log.info("Order %s total %d paise exceeds threshold %d paise -> placing on hold",
                 actual_order_id, total_paise, threshold)
        return draft_to_held(
            order_id=actual_order_id,
            business_id=ord_business_id,
            session_id=ord_session_id,
            input_id=effective_input_id,
            conn=conn,
        )

    # 6. Ordinary confirmation: CAS + stock decrement in sorted SKU order
    def _confirm_business_action(tx_conn):
        # Step A: CAS update on status
        cas_row = tx_conn.execute(
            """
            UPDATE orders SET status = 'confirmed'
            WHERE order_id = %s AND business_id = %s AND session_id = %s AND status = 'draft'
            RETURNING order_id
            """,
            (actual_order_id, ord_business_id, ord_session_id),
        ).fetchone()

        if cas_row is None:
            # Check current status
            curr = tx_conn.execute(
                "SELECT status FROM orders WHERE order_id = %s",
                (actual_order_id,),
            ).fetchone()
            if curr and curr[0] == "confirmed":
                raise AlreadyResolvedError()
            raise StaleQuoteError("Order is no longer in draft status")

        # Step B: Deterministic stock decrement in sorted SKU order
        sorted_items = sorted(items, key=lambda x: x["sku"])
        for it in sorted_items:
            sku = it["sku"]
            qty = it["qty"]
            unit_price = it["unit_price_paise"]
            rem_stock = decrement_stock(tx_conn, ord_business_id, sku, qty, unit_price)
            if rem_stock is None:
                log.warning("Stock decrement failed for SKU %s (qty %d, price %d)", sku, qty, unit_price)
                raise StaleQuoteError(f"Insufficient stock or price mismatch for SKU {sku}")

        # Step C: Create invoice
        invoice_id = str(uuid.uuid4())
        inv_payload = {
            "order_id": actual_order_id,
            "quote_code": quote_code,
            "business_id": ord_business_id,
            "session_id": ord_session_id,
            "total_paise": total_paise,
            "items": items,
        }
        tx_conn.execute(
            """
            INSERT INTO invoices (order_id, invoice_id, payload)
            VALUES (%s, %s, %s)
            """,
            (actual_order_id, invoice_id, json.dumps(inv_payload)),
        )

        return {
            "status": "confirmed",
            "order_id": actual_order_id,
            "invoice_id": invoice_id,
            "total_paise": total_paise,
        }

    reply_payload = {
        "text": f"Order confirmed! Quote {quote_code}. Total: ₹{total_paise / 100:.2f}.",
        "order_id": actual_order_id,
        "status": "confirmed",
    }

    try:
        terminal_result = run_terminal_action(
            input_id=effective_input_id,
            session_id=ord_session_id,
            business_id=ord_business_id,
            kind="confirm",
            business_action=_confirm_business_action,
            reply_payload=reply_payload,
            conn=conn,
        )
        return terminal_result

    except AlreadyResolvedError:
        return {
            "status": "already_resolved",
            "order_id": actual_order_id,
            "order_status": "confirmed",
        }

    except StaleQuoteError as e:
        # Confirmation rolled back cleanly! Record structured stale quote outcome
        log.info("Confirmation failed with stale quote for order %s: %s", actual_order_id, e)
        stale_reply = {
            "text": "Sorry, stock or price for your quote has changed. Please request a new quote.",
            "order_id": actual_order_id,
            "status": "stale_quote",
        }
        stale_result = {
            "status": "stale_quote",
            "reason": str(e),
            "order_id": actual_order_id,
        }
        run_terminal_action(
            input_id=effective_input_id,
            session_id=ord_session_id,
            business_id=ord_business_id,
            kind="stale_quote",
            business_action=lambda tx: stale_result,
            reply_payload=stale_reply,
            conn=conn,
        )
        return stale_result
