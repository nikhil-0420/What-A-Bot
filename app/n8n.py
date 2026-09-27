"""
Held-order notification service (Section G).

Requirement:
  One held-order -> one Telegram notification to a separate owner bot/chat
  or via the n8n webhook hook.
  CRITICAL: Never register a second webhook on the customer-facing bot!
  Resilience: n8n failure must NEVER block or fail order persistence;
  the order must remain fully visible and actionable on the owner page.
"""
import json
import logging
import httpx

from app.config import settings
from app.db import get_conn

log = logging.getLogger(__name__)


def notify_hold(order_id: str, business_id: str) -> bool:
    """
    Synchronous/background entrypoint to notify an owner when an order is placed on hold.
    Catches all network/HTTP exceptions to ensure tenant orders are never rolled back.
    """
    order_data = {}
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT quote_code, total_paise, items, created_at
            FROM orders
            WHERE order_id = %s
            """,
            (order_id,),
        ).fetchone()
        if row:
            order_data = {
                "order_id": str(order_id),
                "business_id": business_id,
                "quote_code": row[0],
                "total_paise": row[1],
                "items": row[2],
                "created_at": str(row[3]),
            }

    success = False
    # 1. Dispatch to n8n webhook if configured
    if settings.n8n_webhook_url:
        headers = {
            "Content-Type": "application/json",
            "X-N8N-Shared-Secret": settings.n8n_shared_secret,
        }
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(
                    settings.n8n_webhook_url,
                    json={"event": "order_held", "data": order_data},
                    headers=headers,
                )
                if resp.status_code in (200, 201, 204):
                    log.info("Successfully notified n8n for held order %s", order_id)
                    success = True
                else:
                    log.warning("n8n webhook returned status %s for order %s", resp.status_code, order_id)
        except Exception:
            log.exception("Failed to dispatch held order %s to n8n webhook — owner page still authoritative", order_id)

    # 2. Dispatch to separate owner Telegram bot/chat if configured
    # NOTE: Strictly sends outbound to separate owner bot, never registers a second webhook
    if settings.owner_telegram_bot_token and settings.owner_telegram_chat_id:
        url = f"https://api.telegram.org/bot{settings.owner_telegram_bot_token}/sendMessage"
        total_inr = (order_data.get("total_paise", 0)) / 100.0
        text = (
            f"⚠️ [ORDER HELD] Order {order_data.get('quote_code', order_id)} for business {business_id} "
            f"needs review! Amount: ₹{total_inr:.2f}"
        )
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(
                    url,
                    json={"chat_id": settings.owner_telegram_chat_id, "text": text},
                )
                if resp.status_code in (200, 201) and resp.json().get("ok"):
                    log.info("Successfully sent held-order Telegram alert for order %s", order_id)
                    success = True
                else:
                    log.warning("Owner bot alert failed for order %s: %s", order_id, resp.text)
        except Exception:
            log.exception("Failed to send Telegram alert to owner bot for order %s", order_id)

    # Record event in events table
    try:
        with get_conn() as conn:
            with conn.transaction():
                conn.execute(
                    """
                    INSERT INTO events (input_id, kind, data)
                    VALUES (%s, 'n8n_notify_attempt', %s)
                    """,
                    (
                        order_data.get("quote_code", str(order_id)),
                        json.dumps({
                            "order_id": str(order_id),
                            "business_id": business_id,
                            "success": success,
                            "n8n_configured": bool(settings.n8n_webhook_url),
                            "owner_bot_configured": bool(settings.owner_telegram_bot_token),
                        }),
                    ),
                )
    except Exception:
        log.exception("Failed to record n8n event in DB")

    return success
