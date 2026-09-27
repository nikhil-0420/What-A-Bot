"""Section E tool contract -- signature is fixed, implement the body."""
from typing import Literal
import logging

from app.db import get_conn

log = logging.getLogger(__name__)


def finish_reply(
    kind: Literal["clarification", "faq", "needs_owner"],
    text: str,
    *,
    input_id: str,
    session_id: str,
    business_id: str,
) -> dict:
    """
    Persists a non-terminal reply into message_outcomes and outbox.

    Returns:
        {"kind": "PersistedReply", "outcome_kind": kind, "text": text}

    This is the ONLY path for agent replies that don't commit an order/booking.
    Always called at the end of a turn — never leave a turn without a persisted
    outcome. On quota/error paths, kind='needs_owner'.

    NOTE: input_id / session_id / business_id are injected by run_agent_turn —
    they are NEVER model-supplied arguments.
    """
    with get_conn() as conn:
        with conn.transaction():
            # Write the outcome row
            conn.execute(
                """
                INSERT INTO message_outcomes (input_id, order_id, kind, result)
                VALUES (%s, NULL, %s, %s::jsonb)
                ON CONFLICT (input_id) DO NOTHING
                """,
                (input_id, kind, __import__("json").dumps({"text": text})),
            )

            # Look up destination for the outbox
            session_row = conn.execute(
                "SELECT customer_phone, destination FROM sessions WHERE session_id = %s",
                (session_id,),
            ).fetchone()

            if session_row:
                customer_phone, destination = session_row
                event_key = f"reply:{input_id}"
                conn.execute(
                    """
                    INSERT INTO outbox (
                        event_key, input_id, session_id, business_id,
                        payload, state
                    ) VALUES (%s, %s, %s, %s, %s::jsonb, 'pending')
                    ON CONFLICT (event_key) DO NOTHING
                    """,
                    (
                        event_key,
                        input_id,
                        session_id,
                        business_id,
                        __import__("json").dumps({"to": customer_phone, "text": text}),
                    ),
                )

            # Mark inbox completed
            conn.execute(
                "UPDATE inbox SET status = 'completed' WHERE input_id = %s",
                (input_id,),
            )

    log.info("finish_reply kind=%s input_id=%s", kind, input_id)
    return {"kind": "PersistedReply", "outcome_kind": kind, "text": text}
