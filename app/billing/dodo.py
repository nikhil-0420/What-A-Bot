import logging
import json
import hmac
import hashlib
import httpx
from fastapi import APIRouter, HTTPException, Request, Header
from app.db import get_conn
from app.config import settings

log = logging.getLogger(__name__)
router = APIRouter(tags=["billing"])

@router.post("/businesses/{id}/billing/checkout")
async def create_checkout(id: str):
    url = "https://live.dodopayments.com/api/payment-links"
    
    payload = {
        "product_id": "prod_12345", # Replace with actual Dodo product ID when known
        "metadata": {
            "business_id": id
        }
    }
    
    headers = {
        "Authorization": f"Bearer {settings.dodo_api_key}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers)
        
        if response.status_code != 200:
            log.error(f"Dodo API Error: {response.text}")
            raise HTTPException(status_code=400, detail="Failed to create checkout")
            
        data = response.json()
        return {"checkout_url": data.get("url")}

@router.get("/businesses/{id}/billing/status")
async def get_billing_status(id: str):
    with get_conn() as conn:
        bus = conn.execute("SELECT business_id FROM businesses WHERE business_id = %s", (id,)).fetchone()
        if not bus:
            raise HTTPException(status_code=404, detail="Business not found")
            
        row = conn.execute("SELECT plan, updated_at FROM business_plan WHERE business_id = %s", (id,)).fetchone()
        if not row:
            conn.execute("INSERT INTO business_plan (business_id, plan) VALUES (%s, 'trial') ON CONFLICT DO NOTHING", (id,))
            conn.commit()
            return {"plan": "trial", "updated_at": None}
        return {"plan": row[0], "updated_at": row[1]}

@router.post("/webhook/dodo")
async def dodo_webhook(request: Request, dodo_signature: str = Header(None)):
    payload = await request.body()
    
    if not dodo_signature:
        raise HTTPException(status_code=401, detail="Missing signature")
        
    expected_signature = hmac.new(
        settings.dodo_webhook_secret.encode('utf-8'),
        payload,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, dodo_signature):
        raise HTTPException(status_code=401, detail="Invalid signature")
        
    try:
        data = json.loads(payload)
        event_id = data.get("event_id")
        kind = data.get("event_type")
        business_id = data.get("data", {}).get("metadata", {}).get("business_id")
        
        if not event_id or not business_id:
            return {"status": "ignored"}
            
    except Exception:
        raise HTTPException(status_code=400, detail="Bad payload")
        
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO billing_events (business_id, dodo_event_id, kind, status, payload) VALUES (%s, %s, %s, %s, %s)",
                (business_id, event_id, kind, "processed", json.dumps(data))
            )
        except Exception:
            conn.rollback()
            return {"status": "already processed or deduplicated"}

        if kind == "payment.succeeded":
            conn.execute(
                "INSERT INTO business_plan (business_id, plan, updated_at) VALUES (%s, 'pro_paid', now()) "
                "ON CONFLICT (business_id) DO UPDATE SET plan = 'pro_paid', updated_at = now()",
                (business_id,)
            )
        conn.commit()
        
    return {"status": "success"}
