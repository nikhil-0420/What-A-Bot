"""Section E tool contract -- signature is fixed, implement the body."""
import logging

from app.memory import breeth_adapter

log = logging.getLogger(__name__)


def answer_faq(
    question: str,
    *,
    business_id: str,
    session_id: str,
) -> dict:
    """
    Looks up a FAQ answer for the given question.

    Strategy:
      1. Pull business FAQ JSON from DB (businesses.faq column) — always
         authoritative for factual business info.
      2. Supplement with Breeth context if available (customer prefs,
         past interactions) — untrusted, never overrides DB facts.
      3. If no match found, return NeedsOwner so the owner is notified.

    Returns one of:
        {"kind": "SupportedAnswer", "text": str}
        {"kind": "NeedsOwner", "reason": str}

    NOTE: business_id / session_id are injected by run_agent_turn — NEVER
    model-supplied arguments.
    """
    from app.db import get_conn
    import json

    # ── Step 1: Pull business FAQ from DB (always authoritative) ─────────────
    faq_data: dict = {}
    with get_conn() as conn:
        row = conn.execute(
            "SELECT faq FROM businesses WHERE business_id = %s",
            (business_id,),
        ).fetchone()
        if row and row[0]:
            faq_data = row[0] if isinstance(row[0], dict) else json.loads(row[0])

    # Simple keyword match against FAQ entries
    # FAQ shape: {"question text": "answer text", ...}  (or list of {q, a} objects)
    answer_text = _match_faq(question, faq_data)

    if answer_text:
        log.info("answer_faq DB hit for business=%s", business_id)
        _try_store_breeth(business_id, session_id, question, answer_text)
        return {"kind": "SupportedAnswer", "text": answer_text}

    # ── Step 2: Try Breeth context (untrusted supplement) ────────────────────
    try:
        breeth_ctx = breeth_adapter.get_context(business_id, session_id)
        breeth_faq = breeth_ctx.get("faq_hints", {})
        answer_text = _match_faq(question, breeth_faq)
        if answer_text:
            log.info("answer_faq Breeth hit for business=%s", business_id)
            return {"kind": "SupportedAnswer", "text": answer_text}
    except NotImplementedError:
        # BLOCKED: Breeth key not confirmed yet — log and continue
        log.warning(
            "answer_faq: Breeth adapter BLOCKED (NotImplementedError) — "
            "falling through to NeedsOwner for business=%s",
            business_id,
        )
    except Exception:
        log.exception("answer_faq: Breeth lookup failed for business=%s", business_id)

    # ── Step 3: No match — escalate to owner ─────────────────────────────────
    log.info("answer_faq NeedsOwner for business=%s question=%r", business_id, question)
    return {
        "kind": "NeedsOwner",
        "reason": f"No FAQ answer found for: {question!r}",
    }


def _match_faq(question: str, faq: dict) -> str | None:
    """
    Simple case-insensitive keyword match.
    FAQ can be:
      - dict: {"question text": "answer text"}
      - list: [{"q": ..., "a": ...}] (normalised below)
    """
    if not faq:
        return None

    # Normalise list format to dict
    if isinstance(faq, list):
        faq = {entry.get("q", ""): entry.get("a", "") for entry in faq}

    q_lower = question.lower()
    for key, value in faq.items():
        if key.lower() in q_lower or q_lower in key.lower():
            return str(value)
    return None


def _try_store_breeth(
    business_id: str, session_id: str, question: str, answer: str
) -> None:
    """Best-effort: store the FAQ interaction in Breeth for future context."""
    try:
        breeth_adapter.update_context(
            business_id,
            session_id,
            {"last_faq_question": question, "last_faq_answer": answer},
        )
    except NotImplementedError:
        # BLOCKED — expected until Breeth key is confirmed
        pass
    except Exception:
        log.exception("answer_faq: Breeth store failed (non-fatal)")
