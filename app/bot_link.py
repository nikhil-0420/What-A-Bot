import datetime
import logging
import secrets
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from app.auth import get_current_owner, check_business_membership
from app.config import settings
from app.db import get_conn

log = logging.getLogger(__name__)
router = APIRouter(tags=["bot_link"])


def issue_token(business_id: str, owner_id: str) -> dict:
    """Issue a single-use bot link token with 10-minute expiry."""
    token = secrets.token_urlsafe(16)
    expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=10)

    with get_conn() as conn:
        with conn.transaction():
            conn.execute(
                """
                INSERT INTO bot_link_tokens (token, business_id, owner_id, expires_at)
                VALUES (%s, %s, %s, %s)
                """,
                (token, business_id, owner_id, expires_at),
            )

    deep_link_url = f"https://t.me/{settings.telegram_bot_username}?start={token}"
    return {
        "token": token,
        "deep_link_url": deep_link_url,
        "expires_at": expires_at.isoformat(),
    }


def consume_token(token: str, chat_id: int) -> tuple[bool, str, str]:
    """
    Consume a single-use token via CAS pattern.
    Returns (success: bool, business_id: str, message: str).
    Guarantees:
      - Valid & unexpired & unconsumed -> consumed_at set, session bound to business_id.
      - Expired or already consumed -> rejected with explanatory message.
    """
    with get_conn() as conn:
        with conn.transaction():
            row = conn.execute(
                """
                UPDATE bot_link_tokens
                SET consumed_at = now(), consumed_by_chat_id = %s
                WHERE token = %s AND consumed_at IS NULL AND expires_at > now()
                RETURNING business_id
                """,
                (chat_id, token),
            ).fetchone()

            if row:
                business_id = row[0]
                # Look up store name
                b_row = conn.execute(
                    "SELECT name FROM businesses WHERE business_id = %s",
                    (business_id,),
                ).fetchone()
                b_name = b_row[0] if b_row else business_id

                # Upsert session binding customer_phone (chat_id) to this business
                conn.execute(
                    """
                    INSERT INTO sessions (customer_phone, destination, active_business_id)
                    VALUES (%s, 'telegram_bot', %s)
                    ON CONFLICT (customer_phone, destination)
                    DO UPDATE SET active_business_id = EXCLUDED.active_business_id
                    """,
                    (str(chat_id), business_id),
                )
                log.info("Token %s consumed by chat %s for business %s", token, chat_id, business_id)
                return True, business_id, f"Successfully connected to {b_name}! You can now send your orders here."

            # CAS failed -- determine exact reason for rejection
            check_row = conn.execute(
                "SELECT consumed_at, expires_at FROM bot_link_tokens WHERE token = %s",
                (token,),
            ).fetchone()

            if not check_row:
                return False, "", "Invalid link token."
            if check_row[0] is not None:
                return False, "", "This link token has already been used."
            return False, "", "This link token has expired. Please request a new link from the store owner."


@router.post("/businesses/{id}/bot-link")
async def create_bot_link(id: str, owner: dict = Depends(get_current_owner)):
    if not check_business_membership(owner["owner_id"], id):
        return JSONResponse(
            status_code=403,
            content={"error": {"code": "forbidden", "message": "You do not have access to this business"}},
        )

    link_data = issue_token(business_id=id, owner_id=owner["owner_id"])
    return link_data
