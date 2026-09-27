"""
Telegram Bot API webhook (Section C).

Flow required by the plan & Section C:
  1. Validate the Telegram secret token.
  2. Parse update_id, message, chat, text.
  3. Form globally unique input_id = 'tg:<bot_id>:<update_id>' (never chat-scoped).
  4. On duplicate update_id: load ALREADY-persisted tenant/session, never trust
     new request context, and dispatch only the accepted row.
  5. Tenant integrity: business_id is bound via sessions.active_business_id, set
     once when a bot_link_tokens row is consumed via /start <token>. Never
     hardcoded, never reset per message, never a global mutable value.
  6. Store telegram_chat_id, telegram_update_id, telegram_message_id separately.
  7. Acknowledge immediately with 200 OK.
"""
import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Request, Response

from app.config import settings
from app.db import get_conn

log = logging.getLogger(__name__)

router = APIRouter()


def _get_bot_id() -> str:
    token = settings.telegram_bot_token
    if ":" in token:
        return token.split(":")[0]
    return "bot"


@router.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    raw_body = await request.body()

    # --- 1. Validate secret token ---
    secret_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if secret_token != settings.telegram_webhook_secret:
        log.warning("Invalid Telegram secret token — rejecting")
        raise HTTPException(status_code=403, detail="Invalid token")

    # --- 2. Parse JSON payload ---
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Handle incoming updates
    update_id = payload.get("update_id")
    if not update_id:
        log.warning("Telegram update missing update_id")
        return Response(status_code=200, content="OK")

    if "message" in payload:
        message = payload["message"]
        message_id = message.get("message_id")
        chat = message.get("chat", {})
        chat_id = chat.get("id")

        # Extract text or voice note
        body_text = message.get("text", "")
        voice = message.get("voice", {})
        voice_file_id = voice.get("file_id") if voice else None

        if not chat_id:
            log.warning("Missing chat id in Telegram update %s", update_id)
            return Response(status_code=200, content="OK")

        bot_id = _get_bot_id()
        # Globally unique input_id per requirement #1
        input_id = f"tg:{bot_id}:{update_id}"
        from_number = str(chat_id)
        to_number = "telegram_bot"

        is_start_cmd = body_text.strip().startswith("/start")
        start_token = None
        if is_start_cmd:
            parts = body_text.strip().split(maxsplit=1)
            if len(parts) > 1:
                start_token = parts[1].strip()

        with get_conn() as conn:
            with conn.transaction():
                # --- 3. Duplicate update_id check ---
                # Load ALREADY-persisted tenant/session, never trust new request context
                existing = conn.execute(
                    """
                    SELECT input_id, session_id, business_id, status
                    FROM inbox
                    WHERE input_id = %s
                    """,
                    (input_id,),
                ).fetchone()

                if existing:
                    log.info("Duplicate update_id %s received (input_id=%s)", update_id, input_id)
                    ex_input_id, ex_session_id, ex_business_id, ex_status = (
                        existing[0],
                        str(existing[1]) if existing[1] else None,
                        existing[2],
                        existing[3],
                    )
                    # Only dispatch if it was in 'received' status
                    if ex_status == "received" and ex_session_id:
                        from app.dispatcher import enqueue_dispatch
                        asyncio.create_task(enqueue_dispatch(ex_input_id, ex_session_id, ex_business_id))
                    return Response(status_code=200, content="OK")

                # --- 4. Handle /start <token> if present ---
                link_msg = None
                if start_token:
                    from app.bot_link import consume_token
                    # CAS-style consumption that binds active_business_id
                    success, bound_business_id, link_msg = consume_token(start_token, chat_id)

                # --- 5. Resolve session & business_id ---
                sess_row = conn.execute(
                    """
                    SELECT session_id, active_business_id
                    FROM sessions
                    WHERE customer_phone = %s AND destination = %s
                    """,
                    (from_number, to_number),
                ).fetchone()

                if sess_row is None:
                    sess_row = conn.execute(
                        """
                        INSERT INTO sessions (customer_phone, destination, active_business_id)
                        VALUES (%s, %s, NULL)
                        RETURNING session_id, active_business_id
                        """,
                        (from_number, to_number),
                    ).fetchone()

                session_id = str(sess_row[0])
                # Tenant strictly comes from sessions.active_business_id
                business_id = sess_row[1]

                # --- 6. Persist to inbox ---
                body_payload = {"text": body_text, "voice_file_id": voice_file_id}
                if link_msg:
                    body_payload["link_response"] = link_msg

                conn.execute(
                    """
                    INSERT INTO inbox (
                        input_id, source, session_id, business_id, body, status,
                        telegram_chat_id, telegram_update_id, telegram_message_id
                    )
                    VALUES (%s, 'telegram', %s, %s, %s, 'received', %s, %s, %s)
                    """,
                    (
                        input_id,
                        session_id,
                        business_id,
                        json.dumps(body_payload),
                        chat_id,
                        update_id,
                        message_id,
                    ),
                )

        # --- 7. Fire-and-forget dispatch ---
        from app.dispatcher import enqueue_dispatch
        asyncio.create_task(enqueue_dispatch(input_id, session_id, business_id))

        log.info("Accepted inbound %s from chat %s (business=%s)", input_id, from_number, business_id)

    # --- 8. Acknowledgment ---
    return Response(status_code=200, content="OK")
