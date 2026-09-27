import datetime
import hashlib
import hmac
import json
import logging
import uuid
import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from app.auth import check_business_membership, get_current_owner
from app.config import settings
from app.db import get_conn

log = logging.getLogger(__name__)
router = APIRouter(tags=["billing"])


@router.post("/businesses/{id}/billing/checkout")
async def create_checkout(id: str, owner: dict = Depends(get_current_owner)):
    with get_conn() as conn:
        biz = conn.execute("SELECT business_id FROM businesses WHERE business_id = %s", (id,)).fetchone()
        if not biz:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "not_found", "message": f"Business {id} not found"}},
            )
        if not check_business_membership(owner["owner_id"], id):
            return JSONResponse(
                status_code=403,
                content={"error": {"code": "forbidden", "message": "You do not have access to this business"}},
            )

    checkout_url = None
    event_id = str(uuid.uuid4())

    # Try live Dodo Payments API if API key is configured
    if settings.dodo_api_key and settings.dodo_api_key.strip():
        url = "https://live.dodopayments.com/api/payment-links"
        payload = {
            "product_id": "prod_retailer_pro",
            "metadata": {"business_id": id, "owner_id": str(owner.get("owner_id"))},
        }
        headers = {
            "Authorization": f"Bearer {settings.dodo_api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(url, json=payload, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    checkout_url = data.get("url") or data.get("payment_link")
                else:
                    log.warning("Dodo API returned status %d: %s", response.status_code, response.text)
        except Exception as exc:
            log.warning("Dodo API connection failed: %s", exc)

    # If Dodo live API key not configured or unavailable, use hosted test checkout
    if not checkout_url:
        checkout_url = f"https://test.dodopayments.com/buy/{id}?plan=pro_monthly&session={event_id[:12]}"

    # Record checkout initiation in billing_events for transparency
    with get_conn() as conn:
        with conn.transaction():
            conn.execute(
                """
                INSERT INTO billing_events (event_id, business_id, dodo_event_id, kind, status, payload)
                VALUES (%s, %s, %s, 'checkout_initiated', 'pending', %s)
                """,
                (
                    event_id,
                    id,
                    f"chk_{event_id[:8]}",
                    json.dumps({"checkout_url": checkout_url, "business_id": id}),
                ),
            )

    return {"checkout_url": checkout_url}


@router.get("/businesses/{id}/billing/status")
async def get_billing_status(id: str, owner: dict = Depends(get_current_owner)):
    with get_conn() as conn:
        biz = conn.execute("SELECT business_id FROM businesses WHERE business_id = %s", (id,)).fetchone()
        if not biz:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "not_found", "message": f"Business {id} not found"}},
            )
        if not check_business_membership(owner["owner_id"], id):
            return JSONResponse(
                status_code=403,
                content={"error": {"code": "forbidden", "message": "You do not have access to this business"}},
            )

        row = conn.execute("SELECT plan, updated_at FROM business_plan WHERE business_id = %s", (id,)).fetchone()
        if not row:
            with conn.transaction():
                conn.execute(
                    "INSERT INTO business_plan (business_id, plan) VALUES (%s, 'trial') ON CONFLICT DO NOTHING",
                    (id,),
                )
            return {"plan": "trial", "updated_at": None}

        updated_at_str = row[1].isoformat() if row[1] else None
        return {"plan": row[0], "updated_at": updated_at_str}


@router.post("/webhook/dodo")
async def dodo_webhook(request: Request, dodo_signature: str = Header(None)):
    payload = await request.body()

    if not dodo_signature:
        return JSONResponse(status_code=401, content={"error": {"code": "unauthorized", "message": "Missing signature"}})

    expected_signature = hmac.new(
        settings.dodo_webhook_secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, dodo_signature):
        return JSONResponse(status_code=401, content={"error": {"code": "unauthorized", "message": "Invalid signature"}})

    try:
        data = json.loads(payload)
        event_id = data.get("event_id")
        kind = data.get("event_type")
        business_id = data.get("data", {}).get("metadata", {}).get("business_id")

        if not event_id or not business_id:
            return {"status": "ignored"}
    except Exception:
        return JSONResponse(status_code=400, content={"error": {"code": "bad_request", "message": "Bad payload"}})

    with get_conn() as conn:
        try:
            with conn.transaction():
                conn.execute(
                    "INSERT INTO billing_events (business_id, dodo_event_id, kind, status, payload) VALUES (%s, %s, %s, %s, %s)",
                    (business_id, event_id, kind, "processed", json.dumps(data)),
                )
        except Exception:
            return {"status": "already processed or deduplicated"}

        if kind == "payment.succeeded":
            with conn.transaction():
                conn.execute(
                    "INSERT INTO business_plan (business_id, plan, updated_at) VALUES (%s, 'test_paid', now()) "
                    "ON CONFLICT (business_id) DO UPDATE SET plan = 'test_paid', updated_at = now()",
                    (business_id,),
                )

    return {"status": "success"}
