from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from app.db import get_conn
from app.auth import get_current_owner, check_business_membership
from pydantic import BaseModel

router = APIRouter(prefix="/businesses")

@router.get("/{id}/catalog")
async def get_catalog(id: str, owner: dict = Depends(get_current_owner)):
    with get_conn() as conn:
        biz = conn.execute(
            "SELECT business_type FROM businesses WHERE business_id = %s",
            (id,)
        ).fetchone()
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

        business_type = biz[0]
        if business_type == "service":
            rows = conn.execute(
                "SELECT service_id, name, duration_minutes, price_paise FROM services WHERE business_id = %s ORDER BY service_id",
                (id,),
            ).fetchall()
            return [
                {
                    "sku": r[0],
                    "name": r[1],
                    "brand": "Service",
                    "ruling": "service",
                    "size": f"{r[2]} mins",
                    "price_paise": r[3],
                    "qty": 1,
                }
                for r in rows
            ]
        else:
            rows = conn.execute(
                "SELECT sku, name, brand, ruling, size, unit_price_paise, qty FROM catalog WHERE business_id = %s ORDER BY sku",
                (id,),
            ).fetchall()
            return [
                {
                    "sku": r[0],
                    "name": r[1],
                    "brand": r[2] or "",
                    "ruling": r[3] or "",
                    "size": r[4] or "",
                    "price_paise": r[5],
                    "qty": r[6],
                }
                for r in rows
            ]

@router.post("/{id}/catalog")
async def add_catalog(id: str, data: dict, owner: dict = Depends(get_current_owner)):
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

        with conn.transaction():
            conn.execute("""
                INSERT INTO catalog (business_id, sku, name, brand, ruling, size, unit_price_paise, qty)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (business_id, sku) DO UPDATE SET qty = catalog.qty + EXCLUDED.qty
            """, (id, data['sku'], data['name'], data.get('brand', ''), data.get('ruling', ''), data.get('size', ''), data['price_paise'], data['qty']))
    return {"status": "ok"}

@router.get("/{id}/services")
async def get_services(id: str, owner: dict = Depends(get_current_owner)):
    with get_conn() as conn:
        biz = conn.execute("SELECT business_type FROM businesses WHERE business_id = %s", (id,)).fetchone()
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

        rows = conn.execute(
            "SELECT service_id, name, duration_minutes, price_paise FROM services WHERE business_id = %s ORDER BY service_id",
            (id,),
        ).fetchall()
        return [{"service_id": r[0], "name": r[1], "duration_minutes": r[2], "price_paise": r[3]} for r in rows]

@router.get("/{id}/slots")
async def get_slots(id: str, service_id: str = None):
    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            if service_id:
                cur.execute("SELECT slot_id, starts_at, capacity FROM service_slots WHERE business_id = %s AND service_id = %s", (id, service_id))
            else:
                cur.execute("SELECT slot_id, starts_at, capacity FROM service_slots WHERE business_id = %s", (id,))
            rows = cur.fetchall()
            return [{"slot_id": r[0], "starts_at": r[1].isoformat(), "capacity": r[2]} for r in rows]

@router.get("/{id}/orders")
async def get_orders(id: str, status: str = None):
    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            query = "SELECT booking_id, status, total_paise, created_at FROM bookings WHERE business_id = %s"
            args = [id]
            if status:
                query += " AND status = %s"
                args.append(status)
            cur.execute(query, args)
            rows = cur.fetchall()
            return [{"order_id": r[0], "status": r[1], "total_paise": r[2], "created_at": r[3].isoformat()} for r in rows]

@router.get("/{id}/holds")
async def get_holds(id: str):
    return await get_orders(id, "held")

@router.post("/{id}/holds")
async def resolve_hold(id: str, data: dict):
    # data: {order_id: str, approve: bool}
    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            new_status = "confirmed" if data.get("approve") else "cancelled"
            cur.execute("UPDATE bookings SET status = %s WHERE booking_id = %s AND business_id = %s", (new_status, data['order_id'], id))
            conn.commit()
    return {"status": "ok"}
