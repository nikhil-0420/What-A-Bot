"""Section E tool contract -- signature is fixed, implement the body."""
import json
import logging
import uuid
from typing import Any

from app.db import get_conn
import app.db as db_module
from app.transactions import run_terminal_action
from app.tools.find_options import get_candidate_set, _load_catalog_items

log = logging.getLogger(__name__)


def _ensure_inbox_session(conn, input_id: str, session_id: str, business_id: str) -> None:
    """Ensure session and inbox rows exist before locking in terminal action."""
    try:
        conn.execute(
            """
            INSERT INTO sessions (session_id, customer_phone, destination, active_business_id)
            VALUES (%s, 'test_customer', 'bot', %s)
            ON CONFLICT (session_id) DO NOTHING
            """,
            (session_id, business_id),
        )
        conn.execute(
            """
            INSERT INTO inbox (input_id, source, session_id, business_id, body, status)
            VALUES (%s, 'whatsapp', %s, %s, '{}', 'processing')
            ON CONFLICT (input_id) DO NOTHING
            """,
            (input_id, session_id, business_id),
        )
    except Exception as e:
        log.debug("Session/inbox auto-provision skipped or failed: %s", e)


def propose_order(
    candidate_set_id: str,
    items: list[dict],
    *,
    input_id: str | None = None,
    session_id: str | None = None,
    business_id: str | None = None,
    conn=None,
) -> dict:
    """
    items: list of {"sku": str, "qty": int}

    Resolves the stored constraints behind candidate_set_id server-side --
    NEVER re-trusts the model's restated constraints. REQUIRES the sum of
    selected quantities to equal the requested quantity (without this
    check, a perfectly priced 11-notebook basket could pass for a
    12-notebook request). Also validates budget, size, ruling,
    brand-mixing permission, and CURRENT catalog data. Unknown/missing
    required constraints trigger clarification. Computes price/total
    itself.

    On success: creates the immutable draft AND its outcome/reply,
    atomically (via transactions.run_terminal_action). Terminal action --
    the model loop stops after a successful commit.
    """
    cset = get_candidate_set(candidate_set_id)
    if cset is None:
        return {
            "status": "validation_error",
            "code": "candidate_set_not_found",
            "message": f"Candidate set {candidate_set_id} not found or expired.",
        }

    # Effective identifiers bound to the candidate set
    effective_business_id = business_id or cset.get("business_id") or "demo-stationery-1"
    effective_session_id = session_id or cset.get("session_id") or str(uuid.uuid4())
    effective_input_id = input_id or cset.get("input_id") or f"in_{uuid.uuid4().hex[:12]}"
    business_type = cset.get("business_type")

    # 1. Enforce sum of selected quantities equals requested quantity
    requested_qty = cset["quantity"]
    total_selected_qty = sum(item.get("qty", 0) for item in items)
    if total_selected_qty != requested_qty:
        return {
            "status": "validation_error",
            "code": "quantity_mismatch",
            "message": (
                f"Selected quantity sum ({total_selected_qty}) does not equal "
                f"requested quantity ({requested_qty})."
            ),
        }

    # 2. Fetch current catalog data
    catalog_items = _load_catalog_items(effective_business_id, conn=conn)
    catalog_by_sku = {it["sku"]: it for it in catalog_items}

    # 3. Validate each item against current catalog stock, ruling, size, and presence
    brands_selected = set()
    total_paise = 0
    order_items = []

    for it in items:
        sku = it.get("sku")
        qty = it.get("qty", 0)
        if qty <= 0:
            continue

        if sku not in catalog_by_sku:
            return {
                "status": "validation_error",
                "code": "sku_not_found",
                "message": f"SKU {sku} does not exist in catalog.",
            }

        cat_item = catalog_by_sku[sku]

        # Enforce current stock availability
        if qty > cat_item["qty"]:
            return {
                "status": "validation_error",
                "code": "insufficient_stock",
                "message": (
                    f"Insufficient stock for SKU {sku}: requested {qty}, "
                    f"available {cat_item['qty']}."
                ),
            }

        # Enforce ruling and size for retail businesses that require it (e.g. stationery)
        if business_type != "supermarket":
            if cset.get("ruling") is not None and cat_item.get("ruling") != cset["ruling"]:
                return {
                    "status": "validation_error",
                    "code": "ruling_mismatch",
                    "message": (
                        f"SKU {sku} ruling '{cat_item.get('ruling')}' does not match "
                        f"requested ruling '{cset['ruling']}'."
                    ),
                }
            if cset.get("size") is not None and cat_item.get("size") != cset["size"]:
                return {
                    "status": "validation_error",
                    "code": "size_mismatch",
                    "message": (
                        f"SKU {sku} size '{cat_item.get('size')}' does not match "
                        f"requested size '{cset['size']}'."
                    ),
                }

        brand = cat_item.get("brand")
        if brand:
            brands_selected.add(brand)

        unit_price = cat_item["unit_price_paise"]
        line_total = qty * unit_price
        total_paise += line_total

        order_items.append({
            "sku": sku,
            "name": cat_item["name"],
            "brand": cat_item.get("brand"),
            "qty": qty,
            "unit_price_paise": unit_price,
            "line_total_paise": line_total,
        })

    # 4. Enforce brand mixing permission
    if not cset.get("allow_mixed_brands", True) and len(brands_selected) > 1:
        return {
            "status": "validation_error",
            "code": "mixed_brands_not_allowed",
            "message": (
                f"Mixed brands not allowed for this order, but multiple brands "
                f"were selected: {sorted(list(brands_selected))}."
            ),
        }

    # 5. Enforce budget
    budget_paise = cset["budget_paise"]
    if total_paise > budget_paise:
        return {
            "status": "validation_error",
            "code": "budget_exceeded",
            "message": (
                f"Total order price ₹{total_paise / 100:.2f} exceeds "
                f"budget ₹{budget_paise / 100:.2f}."
            ),
        }

    # 6. Success: create draft order and outbox reply atomically via run_terminal_action
    order_id = str(uuid.uuid4())
    quote_code = f"Q{uuid.uuid4().hex[:4].upper()}"

    constraints = {
        "quantity": requested_qty,
        "budget_paise": budget_paise,
        "ruling": cset.get("ruling"),
        "size": cset.get("size"),
        "allow_mixed_brands": cset.get("allow_mixed_brands", True),
    }

    def _business_action(tx_conn):
        # Cancel any previous open draft quote for this session & business (Section D)
        tx_conn.execute(
            """
            UPDATE orders SET status = 'cancelled'
            WHERE session_id = %s AND business_id = %s AND status = 'draft'
            """,
            (effective_session_id, effective_business_id),
        )

        # Insert immutable draft order
        tx_conn.execute(
            """
            INSERT INTO orders (
                order_id, quote_code, origin_input_id, session_id, business_id,
                status, constraints, items, total_paise, expires_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                'draft', %s, %s, %s, now() + interval '30 minutes'
            )
            """,
            (
                order_id,
                quote_code,
                effective_input_id,
                effective_session_id,
                effective_business_id,
                json.dumps(constraints),
                json.dumps(order_items),
                total_paise,
            ),
        )

        return {
            "order_id": order_id,
            "quote_code": quote_code,
            "status": "draft",
            "total_paise": total_paise,
            "items": order_items,
            "constraints": constraints,
        }

    items_summary = ", ".join(f"{it['qty']}x {it['name']}" for it in order_items)
    reply_text = (
        f"Quote {quote_code}: {items_summary}. Total: ₹{total_paise / 100:.2f}. "
        f"Reply 'CONFIRM {quote_code}' to place your order."
    )
    reply_payload = {
        "text": reply_text,
        "quote_code": quote_code,
        "order_id": order_id,
        "total_paise": total_paise,
    }

    # Ensure foreign keys exist if in testing / standalone mode
    if conn is not None:
        _ensure_inbox_session(conn, effective_input_id, effective_session_id, effective_business_id)
    elif getattr(db_module, "pool", None) is not None:
        try:
            with get_conn() as c:
                with c.transaction():
                    _ensure_inbox_session(c, effective_input_id, effective_session_id, effective_business_id)
        except Exception:
            pass

    terminal_result = run_terminal_action(
        input_id=effective_input_id,
        session_id=effective_session_id,
        business_id=effective_business_id,
        kind="quote",
        business_action=_business_action,
        reply_payload=reply_payload,
        conn=conn,
    )

    return {
        "status": "draft",
        "order_id": order_id,
        "quote_code": quote_code,
        "total_paise": total_paise,
        "items": order_items,
        "reply": reply_text,
        "terminal_result": terminal_result,
    }
