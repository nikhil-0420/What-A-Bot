"""
The terminal-action transaction pattern, verbatim from Section F. This is
the single most consequential-correctness file in the project -- every
terminal action (propose_order success, confirm_order, owner approve/
reject) MUST go through this same pattern. This is exactly the code Astra
reviews at the ~12:30 checkpoint per the coordination plan.

    BEGIN
      Lock inbox row by input_id.
      If message_outcomes exists: return stored result, do not repeat effects.
      Validate the proposed action.
      Perform the business action, if any.
      INSERT message_outcomes.
      INSERT outbox (unique event_key).
      UPDATE inbox SET status = 'completed'.
    COMMIT

The real guarantee: one committed outcome per accepted input -- not "the
agent only ever runs once." Inference may legitimately re-run after a
crash; it just can never produce a second business effect, because it
re-hits the message_outcomes check first.

No model/network call may run inside this transaction -- the model has
already decided by the time this function is called.
"""
import json
import logging
import uuid

from app.db import get_conn

log = logging.getLogger(__name__)


def run_terminal_action(
    input_id: str,
    session_id: str,
    business_id: str,
    kind: str,
    business_action,
    reply_payload: dict,
    conn=None,
) -> dict:
    """
    Execute the Section F terminal-action transaction.

    business_action: a callable(conn) that performs the actual DB-side effect
    (create draft order, flip to confirmed via CAS, decrement stock, etc.)
    and returns the result dict to store in message_outcomes. It receives the
    open connection so it participates in the same transaction. May be None
    for actions with no business-side effect (echo, faq, clarification).

    reply_payload: the outbox message payload (dict with 'text' and/or
    'to' fields — the sender resolves the destination from the session).

    Returns the result dict (either freshly created or replayed from
    message_outcomes).
    """
    event_key = f"{input_id}:{kind}"
    outbox_id = str(uuid.uuid4())

    def _execute_in_tx(tx_conn):
        with tx_conn.transaction():
            # 1. Lock the inbox row and validate session_id and business_id
            row = tx_conn.execute(
                "SELECT status, session_id, business_id FROM inbox WHERE input_id = %s FOR UPDATE",
                (input_id,),
            ).fetchone()

            if row is None:
                raise ValueError(f"No inbox row for input_id={input_id}")

            status, inbox_session_id, inbox_business_id = row
            if str(inbox_session_id) != str(session_id):
                raise ValueError(
                    f"Session mismatch for input_id={input_id}: expected {session_id}, got {inbox_session_id}"
                )
            if str(inbox_business_id) != str(business_id):
                raise ValueError(
                    f"Business mismatch for input_id={input_id}: expected {business_id}, got {inbox_business_id}"
                )

            # 2. Check for existing outcome — replay guard
            existing = tx_conn.execute(
                "SELECT result FROM message_outcomes WHERE input_id = %s",
                (input_id,),
            ).fetchone()

            if existing is not None:
                log.info("Replay: outcome already exists for %s", input_id)
                return json.loads(existing[0]) if isinstance(existing[0], str) else existing[0]

            # 3. Execute the business action (if any)
            if business_action is not None:
                result = business_action(tx_conn)
            else:
                result = {"kind": kind, "status": "ok"}

            # 4. INSERT message_outcomes
            order_id = result.get("order_id") if isinstance(result, dict) else None
            tx_conn.execute(
                """
                INSERT INTO message_outcomes (input_id, order_id, kind, result)
                VALUES (%s, %s, %s, %s)
                """,
                (input_id, order_id, kind, json.dumps(result)),
            )

            # 5. INSERT outbox (unique event_key)
            tx_conn.execute(
                """
                INSERT INTO outbox (outbox_id, event_key, input_id, session_id,
                                    business_id, payload, state)
                VALUES (%s, %s, %s, %s, %s, %s, 'pending')
                ON CONFLICT (event_key) DO NOTHING
                """,
                (outbox_id, event_key, input_id, session_id, business_id,
                 json.dumps(reply_payload)),
            )

            # 6. UPDATE inbox status to completed
            tx_conn.execute(
                "UPDATE inbox SET status = 'completed' WHERE input_id = %s",
                (input_id,),
            )

            return result

    if conn is not None:
        result = _execute_in_tx(conn)
    else:
        with get_conn() as connection:
            result = _execute_in_tx(connection)

    log.info("Terminal action committed: input=%s kind=%s", input_id, kind)
    return result


def confirm_order_cas(conn, order_id: str, business_id: str, session_id: str,
                       expected_status: str) -> str | None:
    """
    Section F confirmation CAS:
        UPDATE orders SET status = 'confirmed'
        WHERE order_id = :order_id AND business_id = :business_id
          AND session_id = :session_id AND status = :expected_status
        RETURNING order_id;
    expected_status is 'draft' for ordinary customer confirmation,
    'held' for owner approval.

    Returns order_id on success, None on stale/already-resolved.
    Must be called inside a transaction (the one from run_terminal_action).
    """
    row = conn.execute(
        """
        UPDATE orders SET status = 'confirmed'
        WHERE order_id = %s AND business_id = %s
          AND session_id = %s AND status = %s
        RETURNING order_id
        """,
        (order_id, business_id, session_id, expected_status),
    ).fetchone()
    return str(row[0]) if row else None


def decrement_stock(conn, business_id: str, sku: str, quantity: int,
                     quoted_price_paise: int) -> int | None:
    """
    Section F stock decrement, per SKU, in SORTED SKU ORDER (reduces
    deadlock risk):
        UPDATE catalog SET qty = qty - :quantity, updated_at = now()
        WHERE business_id = :business_id AND sku = :sku
          AND qty >= :quantity AND unit_price_paise = :quoted_price
        RETURNING qty;
    One returned row required per item; any failure rolls back the WHOLE
    confirmation including the status transition. If stock/price changed,
    return None -- never silently substitute.

    Must be called inside a transaction.
    """
    row = conn.execute(
        """
        UPDATE catalog SET qty = qty - %s, updated_at = now()
        WHERE business_id = %s AND sku = %s
          AND qty >= %s AND unit_price_paise = %s
        RETURNING qty
        """,
        (quantity, business_id, sku, quantity, quoted_price_paise),
    ).fetchone()
    return row[0] if row else None


def decrement_slot_capacity(conn, business_id: str, service_id: str,
                            slot_id: str) -> int | None:
    """
    Capacity decrement CAS against service_slots.capacity:
        UPDATE service_slots SET capacity = capacity - 1
        WHERE slot_id = %s AND service_id = %s AND business_id = %s
          AND capacity >= 1
        RETURNING capacity
    Returns remaining capacity on success, None on exhaustion.
    Must be called inside a transaction.
    """
    row = conn.execute(
        """
        UPDATE service_slots SET capacity = capacity - 1
        WHERE slot_id = %s AND service_id = %s AND business_id = %s
          AND capacity >= 1
        RETURNING capacity
        """,
        (slot_id, service_id, business_id),
    ).fetchone()
    return row[0] if row else None

