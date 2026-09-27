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
async def get_slots(id: str, service_id: str = None, owner: dict = Depends(get_current_owner)):
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

        if service_id:
            rows = conn.execute(
                "SELECT slot_id, starts_at, capacity FROM service_slots WHERE business_id = %s AND service_id = %s ORDER BY starts_at",
                (id, service_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT slot_id, starts_at, capacity FROM service_slots WHERE business_id = %s ORDER BY starts_at",
                (id,),
            ).fetchall()
        return [{"slot_id": str(r[0]), "starts_at": r[1].isoformat(), "capacity": r[2]} for r in rows]

@router.get("/{id}/orders")
async def get_orders(id: str, status: str = None, owner: dict = Depends(get_current_owner)):
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

        q_orders = "SELECT order_id::text, status, total_paise, created_at FROM orders WHERE business_id = %s"
        args_orders = [id]
        if status:
            q_orders += " AND status = %s"
            args_orders.append(status)
        q_orders += " ORDER BY created_at DESC"
        order_rows = conn.execute(q_orders, args_orders).fetchall()

        q_bookings = "SELECT booking_id::text, status, total_paise, created_at FROM bookings WHERE business_id = %s"
        args_bookings = [id]
        if status:
            q_bookings += " AND status = %s"
            args_bookings.append(status)
        q_bookings += " ORDER BY created_at DESC"
        booking_rows = conn.execute(q_bookings, args_bookings).fetchall()

        items = [
            {"order_id": str(r[0]), "status": r[1], "total_paise": r[2], "created_at": r[3].isoformat() if r[3] else None}
            for r in order_rows
        ] + [
            {"order_id": str(r[0]), "status": r[1], "total_paise": r[2], "created_at": r[3].isoformat() if r[3] else None}
            for r in booking_rows
        ]
        items.sort(key=lambda x: x["created_at"] or "", reverse=True)
        return items

@router.get("/{id}/holds")
async def get_holds(id: str, owner: dict = Depends(get_current_owner)):
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

        order_rows = conn.execute(
            """
            SELECT order_id::text, status, total_paise, created_at, 'order' as item_type
            FROM orders
            WHERE business_id = %s AND status = 'held'
            ORDER BY created_at DESC
            """,
            (id,),
        ).fetchall()

        booking_rows = conn.execute(
            """
            SELECT booking_id::text, status, total_paise, created_at, 'booking' as item_type
            FROM bookings
            WHERE business_id = %s AND status = 'held'
            ORDER BY created_at DESC
            """,
            (id,),
        ).fetchall()

        all_holds = []
        for r in order_rows:
            all_holds.append({
                "order_id": str(r[0]),
                "status": r[1],
                "total_paise": r[2],
                "created_at": r[3].isoformat() if r[3] else None,
                "item_type": r[4],
            })
        for r in booking_rows:
            all_holds.append({
                "order_id": str(r[0]),
                "status": r[1],
                "total_paise": r[2],
                "created_at": r[3].isoformat() if r[3] else None,
                "item_type": r[4],
            })

        all_holds.sort(key=lambda x: x["created_at"] or "", reverse=True)
        return all_holds

@router.post("/{id}/holds")
async def resolve_hold(id: str, data: dict, owner: dict = Depends(get_current_owner)):
    order_id = data.get("order_id")
    approve = bool(data.get("approve", False))
    if not order_id:
        return JSONResponse(
            status_code=400,
            content={"error": {"code": "bad_request", "message": "Missing order_id"}},
        )

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

        # 1. Check orders table
        ord_row = conn.execute(
            "SELECT order_id, status, total_paise, created_at FROM orders WHERE order_id = %s AND business_id = %s",
            (order_id, id),
        ).fetchone()

        if ord_row:
            from app.holds import owner_resolve_hold
            try:
                res = owner_resolve_hold(order_id=order_id, business_id=id, approve=approve)
                updated = conn.execute(
                    "SELECT order_id::text, status, total_paise, created_at FROM orders WHERE order_id = %s",
                    (order_id,),
                ).fetchone()
                return {
                    "order_id": str(updated[0]),
                    "status": updated[1],
                    "total_paise": updated[2],
                    "created_at": updated[3].isoformat() if updated[3] else None,
                    "resolution": res,
                }
            except ValueError as ve:
                return JSONResponse(
                    status_code=400,
                    content={"error": {"code": "invalid_operation", "message": str(ve)}},
                )

        # 2. Check bookings table
        book_row = conn.execute(
            "SELECT booking_id, status, total_paise, created_at FROM bookings WHERE booking_id = %s AND business_id = %s",
            (order_id, id),
        ).fetchone()

        if book_row:
            curr_status = book_row[1]
            if curr_status in ("confirmed", "cancelled"):
                return {
                    "order_id": str(book_row[0]),
                    "status": curr_status,
                    "total_paise": book_row[2],
                    "created_at": book_row[3].isoformat() if book_row[3] else None,
                    "resolution": {"status": "already_resolved", "order_id": str(book_row[0])},
                }

            new_status = "confirmed" if approve else "cancelled"
            with conn.transaction():
                conn.execute(
                    "UPDATE bookings SET status = %s WHERE booking_id = %s AND business_id = %s",
                    (new_status, order_id, id),
                )
                import json
                conn.execute(
                    "INSERT INTO events (kind, data) VALUES (%s, %s)",
                    (
                        "owner_booking_hold_approved" if approve else "owner_booking_hold_rejected",
                        json.dumps({"booking_id": str(order_id), "business_id": id}),
                    ),
                )
            return {
                "order_id": str(book_row[0]),
                "status": new_status,
                "total_paise": book_row[2],
                "created_at": book_row[3].isoformat() if book_row[3] else None,
                "resolution": {"status": new_status, "order_id": str(book_row[0]), "decision": "approved" if approve else "rejected"},
            }

        return JSONResponse(
            status_code=404,
            content={"error": {"code": "not_found", "message": f"Held order or booking {order_id} not found"}},
        )
