"""
Ordered inbox dispatcher (Section H).

"In-process lock registry, shared by live intake and recovery, processes
each conversation's pending input in order."

The dispatcher pulls 'received' rows ordered by sequence, acquires the
session's in-process lock, and calls run_terminal_action with the
appropriate business action. For this block: echo reply. Later blocks
swap in the real model agent turn.
"""
import asyncio
import json
import logging
import traceback

from app.db import get_conn
from app.transactions import run_terminal_action

log = logging.getLogger(__name__)

# Per-session lock registry — shared by live intake and recovery
_session_locks: dict[str, asyncio.Lock] = {}

MAX_ATTEMPTS = 3
BACKOFF_SECONDS = [2, 5, 15]
POLL_INTERVAL_S = 1.0

_dispatcher_task: asyncio.Task | None = None


def _get_session_lock(session_id: str) -> asyncio.Lock:
    if session_id not in _session_locks:
        _session_locks[session_id] = asyncio.Lock()
    return _session_locks[session_id]


def _cleanup_session_lock(session_id: str) -> None:
    """Remove session lock from registry if not locked and no pending messages remain."""
    lock = _session_locks.get(session_id)
    if lock is not None and not lock.locked():
        waiters = getattr(lock, "_waiters", None)
        if not waiters:
            try:
                import uuid
                try:
                    uuid.UUID(str(session_id))
                    is_uuid = True
                except ValueError:
                    is_uuid = False

                if is_uuid:
                    with get_conn() as conn:
                        remaining = conn.execute(
                            "SELECT 1 FROM inbox WHERE session_id = %s AND status IN ('received', 'processing') LIMIT 1",
                            (session_id,),
                        ).fetchone()
                    if remaining:
                        return

                _session_locks.pop(session_id, None)
            except Exception:
                log.exception("Error cleaning up session lock for %s", session_id)


async def start_dispatcher_loop() -> None:
    """Start the supervised background dispatcher worker."""
    global _dispatcher_task
    _dispatcher_task = asyncio.create_task(_dispatcher_loop())
    log.info("Supervised dispatcher loop started")


async def _dispatcher_loop() -> None:
    """Run continuously, polling due inbox rows respecting next_attempt_at."""
    while True:
        try:
            processed = await dispatch_due_batch()
            if not processed:
                await asyncio.sleep(POLL_INTERVAL_S)
        except asyncio.CancelledError:
            log.info("Dispatcher loop cancelled")
            return
        except Exception:
            log.exception("Dispatcher loop encountered an unexpected error — continuing")
            await asyncio.sleep(POLL_INTERVAL_S)


async def dispatch_due_batch() -> bool:
    """Poll up to 10 'received' inbox rows that are due (respecting next_attempt_at).
    Returns True if at least one row was processed, False if queue was empty/not due."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT input_id, session_id, business_id
            FROM inbox
            WHERE status = 'received'
              AND (next_attempt_at IS NULL OR next_attempt_at <= now())
            ORDER BY sequence
            LIMIT 10
            """
        ).fetchall()

    if not rows:
        return False

    for input_id, session_id, business_id in rows:
        session_id = str(session_id)
        lock = _get_session_lock(session_id)
        async with lock:
            await _process_one(input_id, session_id, business_id)
        _cleanup_session_lock(session_id)

    return True


async def enqueue_dispatch(input_id: str, session_id: str, business_id: str) -> None:
    """Fire-and-forget entry point called by the webhook after persisting
    an inbox row. Acquires the session lock so conversation order is
    preserved, then processes."""
    lock = _get_session_lock(session_id)
    async with lock:
        await _process_one(input_id, session_id, business_id)
    _cleanup_session_lock(session_id)


async def dispatch_pending() -> None:
    """Startup/recovery: pull all 'received' inbox rows that are due ordered by sequence
    and dispatch them. Used by recovery.requeue_interrupted."""
    await dispatch_due_batch()


def retry_attention_row(input_id: str) -> bool:
    """Owner action: reset a row that exhausted retries into 'attention' back to
    'received' so the background worker picks it up again."""
    with get_conn() as conn:
        with conn.transaction():
            row = conn.execute(
                """
                UPDATE inbox
                SET status = 'received', attempts = 0, next_attempt_at = now()
                WHERE input_id = %s AND status = 'attention'
                RETURNING input_id
                """,
                (input_id,),
            ).fetchone()
            if row:
                conn.execute(
                    """
                    INSERT INTO events (input_id, kind, data)
                    VALUES (%s, 'inbox_retry_requested', '{"by": "owner"}'::jsonb)
                    """,
                    (input_id,),
                )
                log.info("Owner reset inbox %s from attention to received", input_id)
                return True
            return False


async def _process_one(input_id: str, session_id: str, business_id: str | None) -> None:
    """Process a single inbox row through the terminal-action pattern.
    Bounded retry with backoff; after MAX_ATTEMPTS, mark 'attention'."""

    # Mark processing and read session details in a single connection checkout
    with get_conn() as conn:
        with conn.transaction():
            row = conn.execute(
                """
                UPDATE inbox SET status = 'processing', attempts = attempts + 1
                WHERE input_id = %s AND status IN ('received', 'processing')
                RETURNING attempts, body, business_id
                """,
                (input_id,),
            ).fetchone()

            if row is None:
                log.info("Skipping %s — already completed or missing", input_id)
                return

            attempt = row[0]
            body = row[1]
            business_id = row[2] or business_id

            session_row = conn.execute(
                "SELECT customer_phone FROM sessions WHERE session_id = %s",
                (session_id,),
            ).fetchone()
            customer_phone = session_row[0] if session_row else ""

    try:
        body_text = body.get("text", "") if isinstance(body, dict) else str(body)

        # Handle unlinked customer session
        if not business_id:
            reply_text = (
                "Welcome! You are not currently connected to a store. "
                "Please use your store link (e.g. /start <token>) to connect."
            )
            reply_payload = {
                "to": customer_phone,
                "text": reply_text,
            }
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                run_terminal_action,
                input_id,
                session_id,
                None,
                "unlinked",
                None,
                reply_payload,
            )
            log.info("Dispatched unlinked session %s → %s", input_id, result)
            return

        # --- Business action: for this block, echo reply ---
        # Later blocks will replace this with run_agent_turn()
        reply_text = f"[echo] Received: {body_text}"
        reply_payload = {
            "to": customer_phone,
            "text": reply_text,
        }

        # Run the real terminal action pattern
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            run_terminal_action,
            input_id,
            session_id,
            business_id,
            "echo",
            None,  # no business-side effect for echo
            reply_payload,
        )
        log.info("Dispatched %s → %s", input_id, result)

    except Exception:
        error_msg = traceback.format_exc()
        log.exception("Error processing %s (attempt %d)", input_id, attempt)

        if attempt >= MAX_ATTEMPTS:
            # Mark attention — never silently stuck in processing, visible on owner page
            with get_conn() as conn:
                with conn.transaction():
                    conn.execute(
                        """
                        UPDATE inbox
                        SET status = 'attention', last_error = %s, next_attempt_at = NULL
                        WHERE input_id = %s
                        """,
                        (error_msg[-500:], input_id),
                    )
                    conn.execute(
                        """
                        INSERT INTO events (input_id, kind, data)
                        VALUES (%s, 'inbox_attention', %s)
                        """,
                        (
                            input_id,
                            json.dumps(
                                {
                                    "session_id": session_id,
                                    "business_id": business_id,
                                    "attempts": attempt,
                                    "error": error_msg[-500:],
                                    "reason": "Exhausted retry attempts",
                                }
                            ),
                        ),
                    )
            log.error("Gave up on %s after %d attempts — marked attention for owner visibility",
                      input_id, attempt)
        else:
            # Reset to received with exponential backoff
            backoff = BACKOFF_SECONDS[min(attempt - 1, len(BACKOFF_SECONDS) - 1)]
            with get_conn() as conn:
                with conn.transaction():
                    conn.execute(
                        """
                        UPDATE inbox SET status = 'received', last_error = %s,
                            next_attempt_at = now() + make_interval(secs => %s)
                        WHERE input_id = %s
                        """,
                        (error_msg[-500:], float(backoff), input_id),
                    )
            log.warning("Will retry %s in %ds (attempt %d of %d)", input_id, backoff, attempt, MAX_ATTEMPTS)

