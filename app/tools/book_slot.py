import json
import logging
import uuid

from app.db import get_conn
import app.db as db_module
from app.transactions import run_terminal_action, decrement_slot_capacity
from app.tools.propose_order import _ensure_inbox_session

log = logging.getLogger(__name__)


class SlotUnavailableError(Exception):
    """Raised when slot capacity is exhausted, rolling back booking transaction."""
    pass


def book_slot(
    service_id: str,
    slot_id: str,
    *,
    input_id: str | None = None,
    session_id: str | None = None,
    business_id: str | None = None,
    conn=None,
) -> dict:
    """
    Capacity allocation on confirm: same CAS-then-decrement pattern as stock,
    against service_slots.capacity, inside run_terminal_action.
    """
    def _fetch_slot(c):
        return c.execute(
            """
            SELECT sl.business_id, sl.service_id, s.name, s.price_paise, sl.slot_id, sl.starts_at, sl.capacity
            FROM service_slots sl
            JOIN services s ON sl.service_id = s.service_id AND sl.business_id = s.business_id
            WHERE sl.slot_id::text = %s AND sl.service_id = %s
            """,
            (str(slot_id), str(service_id)),
        ).fetchone()

    eff_session_id = session_id or str(uuid.uuid4())
    eff_input_id = input_id or f"in_{uuid.uuid4().hex[:12]}"

    row = None
    if conn is not None:
        row = _fetch_slot(conn)
        if row is not None:
            b_id = row[0]
            eff_b = business_id or b_id
            if business_id is None or str(business_id) == str(b_id):
                _ensure_inbox_session(conn, eff_input_id, eff_session_id, eff_b)
    elif getattr(db_module, "pool", None) is not None:
        try:
            with get_conn() as c:
                row = _fetch_slot(c)
                if row is not None:
                    b_id = row[0]
                    eff_b = business_id or b_id
                    if business_id is None or str(business_id) == str(b_id):
                        with c.transaction():
                            _ensure_inbox_session(c, eff_input_id, eff_session_id, eff_b)
        except Exception as e:
            log.warning("Could not fetch service slot %s: %s", slot_id, e)

    if row is None:
        return {
            "status": "slot_unavailable",
            "reason": f"Service slot {slot_id} for service {service_id} not found",
            "slot_id": str(slot_id),
        }

    b_id, s_id, s_name, price_paise, sl_id, starts_at, curr_capacity = row
    eff_business_id = business_id or b_id

    if business_id is not None and str(business_id) != str(b_id):
        return {
            "status": "unauthorized",
            "reason": f"Business mismatch: slot belongs to {b_id}, supplied {business_id}",
            "slot_id": str(slot_id),
        }

    booking_id = str(uuid.uuid4())

    def _booking_action(tx_conn):
        # CAS decrement capacity
        remaining = decrement_slot_capacity(tx_conn, eff_business_id, service_id, str(slot_id))
        if remaining is None:
            raise SlotUnavailableError(f"No capacity remaining for slot {slot_id}")

        tx_conn.execute(
            """
            INSERT INTO bookings (
                booking_id, origin_input_id, session_id, business_id,
                slot_id, status, total_paise
            ) VALUES (
                %s, %s, %s, %s,
                %s, 'confirmed', %s
            )
            """,
            (
                booking_id,
                eff_input_id,
                eff_session_id,
                eff_business_id,
                str(slot_id),
                price_paise,
            ),
        )

        return {
            "status": "confirmed",
            "booking_id": booking_id,
            "service_id": service_id,
            "slot_id": str(slot_id),
            "service_name": s_name,
            "total_paise": price_paise,
            "remaining_capacity": remaining,
        }

    reply_payload = {
        "text": f"Booking confirmed! Service: {s_name}. Slot: {starts_at}. Total: ₹{price_paise / 100:.2f}.",
        "booking_id": booking_id,
        "status": "confirmed",
    }

    try:
        terminal_result = run_terminal_action(
            input_id=eff_input_id,
            session_id=eff_session_id,
            business_id=eff_business_id,
            kind="booking",
            business_action=_booking_action,
            reply_payload=reply_payload,
            conn=conn,
        )
        return terminal_result

    except SlotUnavailableError as e:
        log.info("Booking failed - slot capacity exhausted for slot %s: %s", slot_id, e)
        unavail_reply = {
            "text": "Sorry, this service slot is no longer available. Please choose another slot.",
            "slot_id": str(slot_id),
            "status": "slot_unavailable",
        }
        unavail_result = {
            "status": "slot_unavailable",
            "reason": str(e),
            "slot_id": str(slot_id),
        }
        run_terminal_action(
            input_id=eff_input_id,
            session_id=eff_session_id,
            business_id=eff_business_id,
            kind="slot_unavailable",
            business_action=lambda tx: unavail_result,
            reply_payload=unavail_reply,
            conn=conn,
        )
        return unavail_result
