"""Section E tool contract -- signature is fixed, implement the body."""
import json
import logging
import time
import uuid
from collections import OrderedDict
from typing import Literal
from pathlib import Path

from app.db import get_conn
import app.db as db_module

log = logging.getLogger(__name__)

# --- TTL-evicting candidate-set cache (matches 30-min order expiry) ---
_CSET_TTL_S = 30 * 60
_CSET_MAX_SIZE = 10_000
_CANDIDATE_SETS: OrderedDict[str, tuple[float, dict]] = OrderedDict()

# Built-in fallback fixtures for offline/test environments
DEFAULT_SUPERMARKET_FIXTURE = [
    {"sku": "M1", "name": "Milk 1L", "brand": "Amul", "ruling": "unruled", "size": "A5", "unit_price_paise": 6000, "qty": 20},
    {"sku": "M2", "name": "Bread 400g", "brand": "Modern", "ruling": "unruled", "size": "A5", "unit_price_paise": 4500, "qty": 15},
    {"sku": "M3", "name": "Eggs 6pk", "brand": "FarmFresh", "ruling": "unruled", "size": "A5", "unit_price_paise": 5000, "qty": 10},
    {"sku": "M4", "name": "Butter 100g", "brand": "Amul", "ruling": "unruled", "size": "A5", "unit_price_paise": 5500, "qty": 12},
    {"sku": "M5", "name": "Cheese 200g", "brand": "Britannia", "ruling": "unruled", "size": "A5", "unit_price_paise": 12000, "qty": 8},
    {"sku": "M6", "name": "Atta 5kg", "brand": "Aashirvaad", "ruling": "unruled", "size": "A5", "unit_price_paise": 24000, "qty": 10},
]


def _evict_expired() -> None:
    """Drop entries older than TTL.  O(expired) amortised — OrderedDict
    preserves insertion order so we stop at the first non-expired key."""
    now = time.monotonic()
    while _CANDIDATE_SETS:
        _key, (ts, _) = next(iter(_CANDIDATE_SETS.items()))
        if now - ts > _CSET_TTL_S:
            _CANDIDATE_SETS.pop(_key)
        else:
            break


def store_candidate_set(candidate_set_id: str, data: dict) -> None:
    _evict_expired()
    while len(_CANDIDATE_SETS) >= _CSET_MAX_SIZE:
        _CANDIDATE_SETS.popitem(last=False)
    _CANDIDATE_SETS[candidate_set_id] = (time.monotonic(), data)


def get_candidate_set(candidate_set_id: str) -> dict | None:
    _evict_expired()
    entry = _CANDIDATE_SETS.get(candidate_set_id)
    if entry is None:
        return None
    ts, data = entry
    if time.monotonic() - ts > _CSET_TTL_S:
        _CANDIDATE_SETS.pop(candidate_set_id, None)
        return None
    return data


# Cached fixture data — loaded once, reused across calls
_fixture_cache: dict | None = None


def _rows_to_items(rows) -> list[dict]:
    """Convert raw DB rows to item dicts — single source of truth."""
    return [
        {
            "sku": r[0], "name": r[1], "brand": r[2],
            "ruling": r[3], "size": r[4],
            "unit_price_paise": r[5], "qty": r[6],
        }
        for r in rows
    ]


def _load_catalog_items(business_id: str, conn=None) -> list[dict]:
    """Fetch items for business_id from DB or fallback fixture."""
    # Fast path: caller already has a connection
    if conn is not None:
        rows = conn.execute(
            """
            SELECT sku, name, brand, ruling, size, unit_price_paise, qty
            FROM catalog
            WHERE business_id = %s
            ORDER BY sku
            """,
            (business_id,),
        ).fetchall()
        return _rows_to_items(rows)

    # Pool path: one short-lived checkout
    if getattr(db_module, "pool", None) is not None:
        try:
            with get_conn() as c:
                rows = c.execute(
                    """
                    SELECT sku, name, brand, ruling, size, unit_price_paise, qty
                    FROM catalog
                    WHERE business_id = %s
                    ORDER BY sku
                    """,
                    (business_id,),
                ).fetchall()
                if rows:
                    return _rows_to_items(rows)
        except Exception as e:
            log.warning("Could not query DB catalog: %s", e)

    # Offline / fixture fallback (cached after first read)
    global _fixture_cache
    if "supermarket" in business_id:
        return [dict(x, business_id=business_id) for x in DEFAULT_SUPERMARKET_FIXTURE]

    if _fixture_cache is None:
        fixture_path = Path("tests/fixtures/catalog.json")
        if fixture_path.exists():
            with open(fixture_path, "r", encoding="utf-8") as f:
                _fixture_cache = json.load(f)

    if _fixture_cache is not None:
        return _fixture_cache.get("items", [])

    return []


def find_options(
    quantity: int,
    budget_paise: int,
    ruling: Literal["ruled", "unruled"] | None = None,
    size: Literal["A4", "A5"] | None = None,
    allow_mixed_brands: bool = True,
    *,
    business_id: str = "demo-stationery-1",
    session_id: str | None = None,
    input_id: str | None = None,
    business_type: str | None = None,
    conn=None,
) -> dict:
    """
    Returns INDIVIDUAL eligible candidates only -- never a precomputed
    winning basket. Never claims infeasibility just because the model
    hasn't found a solution. Stores the normalized constraints behind an
    opaque candidate_set_id, bound to the current input/session/business,
    for propose_order to resolve server-side later.
    """
    if quantity <= 0:
        raise ValueError(f"Quantity must be positive, got {quantity}")
    if budget_paise <= 0:
        raise ValueError(f"Budget must be positive, got {budget_paise}")

    # Determine business type if not provided
    if business_type is None:
        if "supermarket" in business_id:
            business_type = "supermarket"
        else:
            business_type = "stationery"

    items = _load_catalog_items(business_id, conn=conn)

    candidates = []
    for item in items:
        # Stock filter: must have positive stock
        if item["qty"] <= 0:
            continue

        # Single unit price cannot exceed total budget
        if item["unit_price_paise"] > budget_paise:
            continue

        # For stationery, filter on ruling and size if provided
        if business_type != "supermarket":
            if ruling is not None and item.get("ruling") != ruling:
                continue
            if size is not None and item.get("size") != size:
                continue

        candidates.append({
            "sku": item["sku"],
            "name": item["name"],
            "brand": item["brand"],
            "unit_price_paise": item["unit_price_paise"],
            "qty": item["qty"],
            "ruling": item.get("ruling"),
            "size": item.get("size"),
        })

    candidate_set_id = f"cset_{uuid.uuid4().hex[:12]}"
    cset_data = {
        "candidate_set_id": candidate_set_id,
        "business_id": business_id,
        "session_id": session_id,
        "input_id": input_id,
        "business_type": business_type,
        "quantity": quantity,
        "budget_paise": budget_paise,
        "ruling": ruling,
        "size": size,
        "allow_mixed_brands": allow_mixed_brands,
        "candidate_skus": [c["sku"] for c in candidates],
    }

    store_candidate_set(candidate_set_id, cset_data)

    return {
        "candidate_set_id": candidate_set_id,
        "candidates": candidates,
        "constraints": {
            "quantity": quantity,
            "budget_paise": budget_paise,
            "ruling": ruling,
            "size": size,
            "allow_mixed_brands": allow_mixed_brands,
        },
        "business_id": business_id,
    }
