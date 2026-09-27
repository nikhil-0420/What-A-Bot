"""
Breeth memory adapter — Shahana owns this file.

STATUS: BLOCKED — Breeth API key not yet confirmed (as of 27 Sept 2026).
  - Interface is implemented against the documented Breeth shape.
  - All methods raise NotImplementedError with a clear BLOCKED message
    until the real key is confirmed by Nikhil.
  - Swap the _call_breeth() internals for real HTTP calls the moment
    the key lands — the interface contract does NOT change.

The adapter is untrusted supplementary context — it NEVER overrides
DB stock/price/confirmation status. A failed or mocked Breeth path
must be explicitly logged; it must NOT be silently dropped.

One real store + one real retrieve is the acceptance bar.
A mocked path does NOT satisfy the event's required-sponsor rule.
"""
import logging
import os
from typing import Any

import httpx

log = logging.getLogger(__name__)

# ── Breeth API config (loaded from env at import time) ───────────────────────
_BREETH_API_KEY = os.getenv("BREETH_API_KEY", "").strip()
_BREETH_BASE_URL = os.getenv("BREETH_BASE_URL", "https://api.breeth.ai/v1").rstrip("/")
_BREETH_TIMEOUT = 5.0  # seconds — never block inference for longer than this

# ── BLOCKED flag ─────────────────────────────────────────────────────────────
_BREETH_AVAILABLE = bool(
    _BREETH_API_KEY and _BREETH_API_KEY not in ("your_breeth_api_key_here", "")
)

if not _BREETH_AVAILABLE:
    log.warning(
        "BREETH BLOCKED: BREETH_API_KEY not set or is placeholder. "
        "Store/retrieve will raise NotImplementedError. "
        "Escalate to Nikhil if not resolved by 1:30 PM."
    )


def update_context(business_id: str, session_id: str, payload: dict) -> None:
    """
    Store interaction context in Breeth for this business + session.

    payload shape (flexible — Breeth stores arbitrary JSON):
        {
            "last_faq_question": str,
            "last_faq_answer": str,
            "last_order_summary": str,   # optional
            "customer_preferences": dict, # optional
        }

    RAISES NotImplementedError if BLOCKED (key not set).
    RAISES RuntimeError on API error (non-fatal caller should log + continue).
    """
    if not _BREETH_AVAILABLE:
        raise NotImplementedError(
            "BREETH BLOCKED: BREETH_API_KEY not confirmed. "
            "update_context is a no-op until the key lands."
        )

    _call_breeth(
        method="POST",
        path="/memory/store",
        json={
            "namespace": _namespace(business_id, session_id),
            "data": payload,
        },
    )
    log.info("Breeth store OK  business=%s session=%s", business_id, session_id)


def get_context(business_id: str, session_id: str) -> dict:
    """
    Retrieve stored context from Breeth for this business + session.

    Returns:
        dict — the stored payload, or {} if nothing stored yet.
        Never returns None; callers can safely call .get() on the result.

    RAISES NotImplementedError if BLOCKED (key not set).
    RAISES RuntimeError on API error (caller should catch and treat as {}).

    CRITICAL: the returned dict is UNTRUSTED CONTEXT.
    DB values (stock, price, confirmation status) always win over anything
    returned here. Never carry one business's context into another session.
    """
    if not _BREETH_AVAILABLE:
        raise NotImplementedError(
            "BREETH BLOCKED: BREETH_API_KEY not confirmed. "
            "get_context returns nothing until the key lands."
        )

    resp = _call_breeth(
        method="GET",
        path="/memory/retrieve",
        params={"namespace": _namespace(business_id, session_id)},
    )
    log.info("Breeth retrieve OK  business=%s session=%s", business_id, session_id)
    return resp.get("data", {}) if isinstance(resp, dict) else {}


# ── Internal helpers ─────────────────────────────────────────────────────────

def _namespace(business_id: str, session_id: str) -> str:
    """
    Stable, cross-session-safe namespace key.
    Uses business_id + session_id so one business NEVER leaks into another.
    """
    return f"whatABot:{business_id}:{session_id}"


def _call_breeth(
    method: str,
    path: str,
    *,
    json: dict | None = None,
    params: dict | None = None,
) -> dict[str, Any]:
    """
    Raw HTTP call to the Breeth API.
    Timeout is bounded at _BREETH_TIMEOUT — never blocks inference.

    TODO(Shahana): Once Nikhil confirms the actual Breeth API shape/docs,
    verify the endpoint paths, auth header name, and response envelope
    against the real docs. Current shape is best-effort from event docs.
    """
    headers = {
        "Authorization": f"Bearer {_BREETH_API_KEY}",
        "Content-Type": "application/json",
    }
    url = f"{_BREETH_BASE_URL}{path}"

    try:
        with httpx.Client(timeout=_BREETH_TIMEOUT) as client:
            resp = client.request(
                method=method,
                url=url,
                headers=headers,
                json=json,
                params=params,
            )
        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"Breeth API error {resp.status_code}: {resp.text[:200]}"
            )
        return resp.json() if resp.content else {}
    except httpx.TimeoutException:
        raise RuntimeError(
            f"Breeth API timeout after {_BREETH_TIMEOUT}s — "
            "treat as no context available"
        )
