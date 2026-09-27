from fastapi import APIRouter
from app.db import get_pool

router = APIRouter(prefix="/businesses")

@router.get("/{id}/evidence")
async def get_evidence(id: str):
    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            # Fetch events (tool events, etc)
            cur.execute("""
                SELECT e.created_at, e.kind, e.data
                FROM events e
                LEFT JOIN inbox i ON e.input_id = i.input_id
                WHERE i.business_id = %s OR e.input_id IS NULL
                ORDER BY e.created_at DESC LIMIT 50
            """, (id,))
            event_rows = cur.fetchall()
            events = [{"type": "event", "timestamp": r[0].isoformat(), "kind": r[1], "data": r[2]} for r in event_rows]

            # Fetch outbox
            cur.execute("""
                SELECT created_at, state, payload, attempt_no
                FROM outbox
                WHERE business_id = %s
                ORDER BY created_at DESC LIMIT 20
            """, (id,))
            outbox_rows = cur.fetchall()
            outbox = [{"type": "outbox", "timestamp": r[0].isoformat(), "state": r[1], "payload": r[2], "attempt": r[3]} for r in outbox_rows]

            # Fetch message outcomes
            cur.execute("""
                SELECT m.created_at, m.kind, m.result
                FROM message_outcomes m
                LEFT JOIN inbox i ON m.input_id = i.input_id
                WHERE i.business_id = %s
                ORDER BY m.created_at DESC LIMIT 20
            """, (id,))
            outcome_rows = cur.fetchall()
            outcomes = [{"type": "outcome", "timestamp": r[0].isoformat(), "kind": r[1], "result": r[2]} for r in outcome_rows]
            
            # Combine all
            all_evidence = events + outbox + outcomes
            all_evidence.sort(key=lambda x: x["timestamp"], reverse=True)
            return all_evidence
