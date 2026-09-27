"""
Independent outbox sender (Section H).

"Claim one pending outbox row -> mark 'sending' -> call Telegram API outside the
transaction -> record SID/state." Ambiguous sends are marked 'unknown', not
auto-retried -- the owner page offers explicit retry with a duplicate-
message warning.
"""
import asyncio
import logging
import httpx
import uuid

from app.config import settings
from app.db import get_conn

log = logging.getLogger(__name__)

POLL_INTERVAL_S = 2.0

_sender_task: asyncio.Task | None = None


async def start_sender_loop() -> None:
    """Start the sender as a background asyncio task."""
    global _sender_task
    _sender_task = asyncio.create_task(_sender_loop())
    log.info("Sender loop started")


async def _sender_loop() -> None:
    """Run forever, polling for pending outbox rows."""
    while True:
        try:
            sent = await send_one_pending()
            if not sent:
                await asyncio.sleep(POLL_INTERVAL_S)
        except asyncio.CancelledError:
            log.info("Sender loop cancelled")
            return
        except Exception:
            log.exception("Sender loop error — will retry")
            await asyncio.sleep(POLL_INTERVAL_S)


def _redact_token(text: str) -> str:
    """Scrub bot token from any logged strings, URLs, or exception messages."""
    if settings.telegram_bot_token and settings.telegram_bot_token in text:
        return text.replace(settings.telegram_bot_token, "[REDACTED_BOT_TOKEN]")
    return text


async def send_one_pending() -> bool:
    """Claim one pending outbox row, send via Telegram API (or mock), record result.
    Returns True if a row was claimed and processed, False if idle."""

    # 1. Claim a pending row inside a short transaction
    claimed = None
    with get_conn() as conn:
        with conn.transaction():
            row = conn.execute(
                """
                SELECT outbox_id, payload, session_id, attempt_no
                FROM outbox
                WHERE state = 'pending'
                ORDER BY created_at
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """,
            ).fetchone()

            if row is None:
                return False

            outbox_id, payload, session_id, attempt_no = (
                str(row[0]), row[1], str(row[2]), row[3]
            )
            new_attempt = attempt_no + 1

            conn.execute(
                """
                UPDATE outbox SET state = 'sending', attempt_no = %s
                WHERE outbox_id = %s
                """,
                (new_attempt, outbox_id),
            )
            claimed = (outbox_id, payload, session_id, new_attempt)

    if claimed is None:
        return False

    outbox_id, payload, session_id, attempt_no = claimed

    # Resolve destination from payload or session
    to_number = payload.get("to", "") if isinstance(payload, dict) else ""
    body_text = payload.get("text", "") if isinstance(payload, dict) else str(payload)

    if not to_number:
        # Fall back to session's customer_phone
        with get_conn() as conn:
            srow = conn.execute(
                "SELECT customer_phone FROM sessions WHERE session_id = %s",
                (session_id,),
            ).fetchone()
        to_number = srow[0] if srow else ""

    # 2. Call API OUTSIDE any transaction
    provider_sid = None
    final_state = "unknown"

    if settings.send_mode == "mock":
        # Mock mode
        provider_sid = f"mock-{uuid.uuid4().hex[:8]}"
        final_state = "accepted"
        log.info("[MOCK SEND] outbox %s to %s: %s", outbox_id, to_number, body_text)
    else:
        # Telegram API
        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        json_data = {
            "chat_id": to_number,
            "text": body_text
        }

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=json_data, timeout=10.0)
                
                if resp.status_code in (200, 201):
                    try:
                        data = resp.json()
                    except Exception:
                        data = {}

                    if data.get("ok") is True:
                        provider_sid = str(data.get("result", {}).get("message_id"))
                        final_state = "accepted"
                        log.info("Sent outbox %s → Telegram Msg ID %s", outbox_id, provider_sid)
                    else:
                        final_state = "failed"
                        log.error("Telegram API returned ok=false for outbox %s: %s", outbox_id, _redact_token(resp.text))
                else:
                    log.error("Telegram API error for outbox %s: %s %s", outbox_id, resp.status_code, _redact_token(resp.text))
                    final_state = "unknown"
                    
        except Exception as exc:
            log.error("Telegram send failed for outbox %s — marking unknown: %s", outbox_id, _redact_token(str(exc)))
            final_state = "unknown"


    # 3. Record result
    with get_conn() as conn:
        with conn.transaction():
            # Still storing in twilio_sid column as requested
            conn.execute(
                """
                UPDATE outbox
                SET state = %s, twilio_sid = %s
                WHERE outbox_id = %s AND attempt_no = %s
                """,
                (final_state, provider_sid, outbox_id, attempt_no),
            )

    return True
