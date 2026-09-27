"""
app/model_agent.py — Gemini agent loop (Shahana owns this file)
================================================================

Implements run_agent_turn: the tool-calling loop that sits between the
Telegram dispatcher and the DB-backed tool implementations.

Model confirmed live: gemini-3.5-flash-lite (FC PASS, 2023ms)
Fallback confirmed:   gemini-3.6-flash       (FC PASS, 2532ms)
Verified: 27 Sept 2026 via scratch/verify_gemini_models.py

Design rules enforced here:
  - Backend context (input_id, session_id, business_id) is injected —
    NEVER a model-editable argument.
  - propose_order / confirm_order / book_slot are TERMINAL: loop stops
    after a successful commit.
  - On quota/timeout failure: persist truthful needs_owner reply via
    finish_reply — NEVER fabricate a result.
  - Breeth is untrusted supplementary context. DB always wins.
  - Never carry one session's context into another.
  - Bounded tool turns (MAX_TOOL_TURNS = 6).
  - Bounded provider timeout (GEMINI_TIMEOUT_S = 20).
  - Bounded rate-limit retry (MAX_RETRIES = 2, exponential backoff).
  - No external network calls inside a DB transaction.
"""
import asyncio
import json
import logging
import time
from typing import Any

import httpx

from app.config import settings
from app.db import get_conn
from app.tools.finish_reply import finish_reply
from app.tools.answer_faq import answer_faq

log = logging.getLogger(__name__)

# ── Tunables ─────────────────────────────────────────────────────────────────
MAX_TOOL_TURNS = 6        # hard cap on model↔tool round-trips per message
GEMINI_TIMEOUT_S = 20.0   # per-call timeout — never block the dispatcher longer
MAX_RETRIES = 2           # on 429/503; exponential backoff: 2s, 4s
RETRY_BACKOFF = [2.0, 4.0]

# ── Terminal tools — loop stops after a successful call to any of these ───────
TERMINAL_TOOLS = {"propose_order", "confirm_order", "book_slot"}

# ── Gemini REST endpoint (v1beta — supports function-calling) ────────────────
_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


# ── Tool schema registry ─────────────────────────────────────────────────────
# Tool schemas are the JSON declarations given to Gemini.
# Backend-only args (input_id, session_id, business_id) are NOT listed here —
# they are injected server-side after the model picks the tool.

_TOOL_SCHEMAS: list[dict] = [
    {
        "name": "find_options",
        "description": (
            "Search the catalog for notebooks matching the customer's constraints. "
            "Returns individual candidates (never a precomputed basket). "
            "Call this FIRST when a customer asks for notebooks."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "quantity":           {"type": "INTEGER", "description": "Number of notebooks requested."},
                "budget_paise":       {"type": "INTEGER", "description": "Maximum total budget in paise (100 paise = ₹1). 0 means no budget constraint."},
                "ruling":             {"type": "STRING",  "enum": ["ruled", "unruled"], "description": "Ruling preference."},
                "size":               {"type": "STRING",  "enum": ["A4", "A5"], "description": "Notebook size."},
                "allow_mixed_brands": {"type": "BOOLEAN", "description": "Whether the customer will accept different brands in one basket."},
            },
            "required": ["quantity", "budget_paise", "ruling", "size", "allow_mixed_brands"],
        },
    },
    {
        "name": "propose_order",
        "description": (
            "Propose a basket of items from the candidates returned by find_options. "
            "TERMINAL: loop ends after a successful commit. "
            "Pass the candidate_set_id from find_options and your chosen items."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "candidate_set_id": {"type": "STRING", "description": "Opaque ID from find_options result."},
                "items": {
                    "type": "ARRAY",
                    "description": "Chosen SKUs and quantities.",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "sku": {"type": "STRING"},
                            "qty": {"type": "INTEGER"},
                        },
                        "required": ["sku", "qty"],
                    },
                },
            },
            "required": ["candidate_set_id", "items"],
        },
    },
    {
        "name": "confirm_order",
        "description": (
            "Confirm a previously proposed order. Only call this when the customer "
            "has explicitly said something like 'confirm' or 'yes, go ahead'. "
            "TERMINAL: loop ends after a successful commit."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "order_id": {"type": "STRING", "description": "The order_id from the draft order to confirm."},
            },
            "required": ["order_id"],
        },
    },
    {
        "name": "book_slot",
        "description": (
            "Book a service slot. TERMINAL: loop ends after a successful commit. "
            "Call only after showing the customer available slots."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "service_id": {"type": "STRING", "description": "The service being booked."},
                "slot_id":    {"type": "STRING", "description": "The specific slot to book."},
            },
            "required": ["service_id", "slot_id"],
        },
    },
    {
        "name": "answer_faq",
        "description": (
            "Answer a general question about the business (hours, policies, etc.). "
            "Do NOT use this for order or booking requests."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "question": {"type": "STRING", "description": "The customer's question, verbatim."},
            },
            "required": ["question"],
        },
    },
    {
        "name": "finish_reply",
        "description": (
            "Send a final reply that is NOT an order or booking — e.g. a clarification "
            "request, an FAQ answer, or an escalation. Always call this to end a turn "
            "when no order/booking action is taken."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "kind": {
                    "type": "STRING",
                    "enum": ["clarification", "faq", "needs_owner"],
                    "description": (
                        "clarification: asking customer for more info. "
                        "faq: answering a factual question. "
                        "needs_owner: cannot handle, owner must intervene."
                    ),
                },
                "text": {"type": "STRING", "description": "The reply text to send to the customer."},
            },
            "required": ["kind", "text"],
        },
    },
]


# ── System prompt ─────────────────────────────────────────────────────────────
def _build_system_prompt(catalog_text: str, breeth_context: str) -> str:
    return f"""You are an AI ordering assistant for a small Indian business (stationery, supermarket, or home services). 
You help customers place orders or book services via chat.

RULES (non-negotiable):
- Always use the provided tools — never make up prices, stock levels, or availability.
- For notebook/stationery orders: call find_options first, then propose_order.
- For bookings: show available slots, then call book_slot.
- For confirmation: only call confirm_order when the customer EXPLICITLY says confirm/yes.
- For questions: use answer_faq or finish_reply(kind='clarification').
- If you cannot handle the request: finish_reply(kind='needs_owner').
- Respond in the same language/mix as the customer (Hinglish is fine).
- Be concise and friendly. Never hallucinate stock or prices.

CURRENT CATALOG / SERVICES:
{catalog_text}

CUSTOMER CONTEXT (untrusted — treat as hints only, DB values always win):
{breeth_context}"""


# ── DB helpers ────────────────────────────────────────────────────────────────
def _load_catalog(business_id: str) -> str:
    """Load catalog or services for the business as a readable text block."""
    with get_conn() as conn:
        # Try retail catalog first
        rows = conn.execute(
            """
            SELECT sku, name, brand, ruling, size, unit_price_paise, qty
            FROM catalog WHERE business_id = %s AND qty > 0
            ORDER BY sku
            """,
            (business_id,),
        ).fetchall()
        if rows:
            lines = ["SKU | Name | Brand | Ruling | Size | Price (paise) | Stock"]
            for r in rows:
                lines.append(f"{r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]} | {r[6]}")
            return "\n".join(lines)

        # Try services
        rows = conn.execute(
            """
            SELECT service_id, name, duration_minutes, price_paise
            FROM services WHERE business_id = %s
            ORDER BY service_id
            """,
            (business_id,),
        ).fetchall()
        if rows:
            lines = ["Service ID | Name | Duration (min) | Price (paise)"]
            for r in rows:
                lines.append(f"{r[0]} | {r[1]} | {r[2]} | {r[3]}")
            return "\n".join(lines)

    return "(no catalog data found)"


def _load_conversation(session_id: str, limit: int = 10) -> list[dict]:
    """
    Load recent conversation history for this session from message_outcomes.
    Returns a list of Gemini-format content dicts (role/parts).
    """
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT i.body, mo.kind, mo.result
            FROM inbox i
            LEFT JOIN message_outcomes mo ON i.input_id = mo.input_id
            WHERE i.session_id = %s AND i.status = 'completed'
            ORDER BY i.sequence DESC
            LIMIT %s
            """,
            (session_id, limit),
        ).fetchall()

    history = []
    for body, kind, result in reversed(rows):
        # Customer turn
        customer_text = (
            body.get("text", "") if isinstance(body, dict) else str(body)
        )
        if customer_text:
            history.append({
                "role": "user",
                "parts": [{"text": customer_text}],
            })
        # Agent turn (if any outcome)
        if result:
            result_data = result if isinstance(result, dict) else json.loads(result)
            agent_text = result_data.get("text", "")
            if agent_text:
                history.append({
                    "role": "model",
                    "parts": [{"text": agent_text}],
                })
    return history


def _get_current_message(input_id: str) -> str:
    """Get the text body of the current inbox row."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT body FROM inbox WHERE input_id = %s",
            (input_id,),
        ).fetchone()
    if not row:
        return ""
    body = row[0]
    return body.get("text", "") if isinstance(body, dict) else str(body)


# ── Gemini API call ───────────────────────────────────────────────────────────
def _call_gemini(
    contents: list[dict],
    system_prompt: str,
    model: str,
    api_key: str,
) -> dict:
    """
    Single synchronous Gemini generateContent call with tool declarations.
    Raises httpx.HTTPStatusError on non-2xx.
    Raises httpx.TimeoutException on timeout.
    """
    url = f"{_GEMINI_BASE}/{model}:generateContent?key={api_key}"
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "tools": [{"function_declarations": _TOOL_SCHEMAS}],
        "tool_config": {"function_calling_config": {"mode": "AUTO"}},
        "generation_config": {
            "temperature": 0.1,   # low temp for deterministic tool calling
            "max_output_tokens": 512,
        },
    }
    with httpx.Client(timeout=GEMINI_TIMEOUT_S) as client:
        resp = client.post(url, json=payload)
    resp.raise_for_status()
    return resp.json()


def _extract_function_call(gemini_response: dict) -> tuple[str, dict] | None:
    """
    Extract the first function call from a Gemini response.
    Returns (function_name, args_dict) or None if the model replied in text.
    """
    candidates = gemini_response.get("candidates", [])
    if not candidates:
        return None
    parts = candidates[0].get("content", {}).get("parts", [])
    for part in parts:
        if "functionCall" in part:
            fc = part["functionCall"]
            return fc.get("name"), fc.get("args", {})
    return None


def _extract_text(gemini_response: dict) -> str:
    """Extract text reply from Gemini response (when no function call)."""
    candidates = gemini_response.get("candidates", [])
    if not candidates:
        return ""
    parts = candidates[0].get("content", {}).get("parts", [])
    return " ".join(p.get("text", "") for p in parts if "text" in p).strip()


# ── Tool dispatcher ───────────────────────────────────────────────────────────
def _dispatch_tool(
    fn_name: str,
    fn_args: dict,
    *,
    input_id: str,
    session_id: str,
    business_id: str,
) -> tuple[dict, bool]:
    """
    Call the actual tool implementation with injected backend context.
    Returns (result_dict, is_terminal).

    Backend context (input_id, session_id, business_id) is injected here —
    the model only supplies the business-logic arguments.
    """
    is_terminal = fn_name in TERMINAL_TOOLS

    if fn_name == "find_options":
        from app.tools.find_options import find_options
        result = find_options(
            quantity=fn_args["quantity"],
            budget_paise=fn_args["budget_paise"],
            ruling=fn_args["ruling"],
            size=fn_args["size"],
            allow_mixed_brands=fn_args["allow_mixed_brands"],
            # injected context:
            business_id=business_id,
            session_id=session_id,
            input_id=input_id,
        )

    elif fn_name == "propose_order":
        from app.tools.propose_order import propose_order
        result = propose_order(
            candidate_set_id=fn_args["candidate_set_id"],
            items=fn_args["items"],
            # injected:
            input_id=input_id,
            session_id=session_id,
            business_id=business_id,
        )

    elif fn_name == "confirm_order":
        from app.tools.confirm_order import confirm_order
        result = confirm_order(
            order_id=fn_args["order_id"],
            # injected:
            input_id=input_id,
            session_id=session_id,
            business_id=business_id,
        )

    elif fn_name == "book_slot":
        from app.tools.book_slot import book_slot
        result = book_slot(
            service_id=fn_args["service_id"],
            slot_id=fn_args["slot_id"],
            # injected:
            input_id=input_id,
            session_id=session_id,
            business_id=business_id,
        )

    elif fn_name == "answer_faq":
        result = answer_faq(
            question=fn_args["question"],
            business_id=business_id,
            session_id=session_id,
        )
        # Non-terminal — but if NeedsOwner, treat as finish_reply
        if result.get("kind") == "NeedsOwner":
            finish_reply(
                kind="needs_owner",
                text="I'm not sure about that — I've flagged it for the owner to answer.",
                input_id=input_id,
                session_id=session_id,
                business_id=business_id,
            )
            return result, True  # terminal (loop ends, owner notified)

    elif fn_name == "finish_reply":
        result = finish_reply(
            kind=fn_args["kind"],
            text=fn_args["text"],
            input_id=input_id,
            session_id=session_id,
            business_id=business_id,
        )
        is_terminal = True  # finish_reply always ends the loop

    else:
        log.warning("Unknown tool called by model: %s — treating as error", fn_name)
        result = {"error": f"Unknown tool: {fn_name}"}

    return result, is_terminal


# ── Main entry point ──────────────────────────────────────────────────────────
async def run_agent_turn(
    input_id: str,
    business_id: str,
    session_id: str,
    message_body: dict,
) -> None:
    """
    Run one full agent turn for an incoming customer message.

    Called by the dispatcher after an inbox row is marked 'processing'.
    This function owns the Gemini ↔ tool loop for one message.

    Contract:
      - ALWAYS ends with a persisted outcome (message_outcomes row).
      - NEVER holds a DB transaction open during inference.
      - NEVER fabricates a result on quota failure.
      - NEVER carries context across sessions or businesses.
    """
    api_key = settings.gemini_api_key or settings.model_api_key
    primary_model = settings.gemini_model or settings.model_name
    fallback_model = settings.gemini_fallback_model or settings.model_fallback_name

    if not api_key:
        log.error("run_agent_turn: GEMINI_API_KEY not set — persisting needs_owner")
        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: finish_reply(
                kind="needs_owner",
                text="Sorry, I'm not available right now. Please try again shortly.",
                input_id=input_id,
                session_id=session_id,
                business_id=business_id,
            ),
        )
        return

    # ── Build context (all DB reads happen BEFORE any inference) ─────────────
    catalog_text = await asyncio.get_event_loop().run_in_executor(
        None, _load_catalog, business_id
    )

    # Breeth context — untrusted, non-blocking, non-fatal
    breeth_text = ""
    try:
        from app.memory import breeth_adapter
        ctx = await asyncio.get_event_loop().run_in_executor(
            None, breeth_adapter.get_context, business_id, session_id
        )
        if ctx:
            breeth_text = json.dumps(ctx, ensure_ascii=False)
    except NotImplementedError:
        log.info("run_agent_turn: Breeth BLOCKED — proceeding without memory context")
    except Exception:
        log.exception("run_agent_turn: Breeth get_context failed (non-fatal)")

    system_prompt = _build_system_prompt(catalog_text, breeth_text or "(none)")

    # Load conversation history + current message
    history = await asyncio.get_event_loop().run_in_executor(
        None, _load_conversation, session_id
    )
    current_text = message_body.get("text", "") if isinstance(message_body, dict) else str(message_body)
    
    # Check for voice note
    voice_file_id = message_body.get("voice_file_id") if isinstance(message_body, dict) else None
    if voice_file_id:
        try:
            from app.voice import download_and_transcribe
            transcript = await download_and_transcribe(voice_file_id)
            current_text = f"[Transcribed Voice Note]: {transcript}"
        except Exception as e:
            log.warning("Voice transcription failed for %s: %s", input_id, e)
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: finish_reply(
                    kind="clarification",
                    text="I couldn't hear that clearly. Could you please type it out?",
                    input_id=input_id,
                    session_id=session_id,
                    business_id=business_id,
                ),
            )
            return

    contents = history + [{"role": "user", "parts": [{"text": current_text}]}]

    log.info(
        "run_agent_turn start input_id=%s business=%s session=%s model=%s history_turns=%d",
        input_id, business_id, session_id, primary_model, len(history),
    )

    # ── Tool-calling loop ─────────────────────────────────────────────────────
    turn = 0
    model = primary_model

    while turn < MAX_TOOL_TURNS:
        turn += 1
        log.debug("Agent turn %d/%d model=%s", turn, MAX_TOOL_TURNS, model)

        # ── Gemini call with retry on 429/503 ────────────────────────────────
        gemini_response = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                gemini_response = await asyncio.get_event_loop().run_in_executor(
                    None,
                    _call_gemini,
                    contents,
                    system_prompt,
                    model,
                    api_key,
                )
                break  # success

            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status == 429 and attempt < MAX_RETRIES:
                    backoff = RETRY_BACKOFF[attempt]
                    log.warning(
                        "Gemini 429 rate limit (attempt %d) — backing off %.1fs",
                        attempt + 1, backoff,
                    )
                    await asyncio.sleep(backoff)
                    continue
                elif status == 503 and attempt < MAX_RETRIES:
                    # Try fallback model on 503
                    if model == primary_model and fallback_model and fallback_model != primary_model:
                        log.warning(
                            "Gemini 503 on %s — switching to fallback %s",
                            model, fallback_model,
                        )
                        model = fallback_model
                        continue
                    backoff = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
                    await asyncio.sleep(backoff)
                    continue
                else:
                    log.error(
                        "Gemini HTTP %d — persisting needs_owner for input_id=%s",
                        status, input_id,
                    )
                    await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: finish_reply(
                            kind="needs_owner",
                            text="Sorry, I'm having trouble right now. Please try again in a moment.",
                            input_id=input_id,
                            session_id=session_id,
                            business_id=business_id,
                        ),
                    )
                    return

            except httpx.TimeoutException:
                log.error(
                    "Gemini timeout after %.1fs — persisting needs_owner for input_id=%s",
                    GEMINI_TIMEOUT_S, input_id,
                )
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: finish_reply(
                        kind="needs_owner",
                        text="I'm taking too long to respond. Please try again shortly.",
                        input_id=input_id,
                        session_id=session_id,
                        business_id=business_id,
                    ),
                )
                return

        if gemini_response is None:
            # All retries exhausted
            log.error("All Gemini retries exhausted for input_id=%s", input_id)
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: finish_reply(
                    kind="needs_owner",
                    text="I'm not available right now. Please try again shortly.",
                    input_id=input_id,
                    session_id=session_id,
                    business_id=business_id,
                ),
            )
            return

        # ── Extract function call or text ─────────────────────────────────────
        fn_call = _extract_function_call(gemini_response)

        if fn_call is None:
            # Model replied in text (shouldn't happen with AUTO mode, but handle it)
            text_reply = _extract_text(gemini_response)
            if not text_reply:
                text_reply = "I'm not sure how to help with that. Please rephrase."
            log.warning(
                "Model replied in text (no fn_call) on turn %d — persisting as clarification",
                turn,
            )
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: finish_reply(
                    kind="clarification",
                    text=text_reply,
                    input_id=input_id,
                    session_id=session_id,
                    business_id=business_id,
                ),
            )
            return

        fn_name, fn_args = fn_call
        log.info("Model called tool: %s args=%s", fn_name, fn_args)

        # ── Execute tool ──────────────────────────────────────────────────────
        try:
            tool_result, is_terminal = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: _dispatch_tool(
                    fn_name,
                    fn_args,
                    input_id=input_id,
                    session_id=session_id,
                    business_id=business_id,
                ),
            )
        except NotImplementedError:
            # Sam's tools not yet implemented — honest error
            log.warning("Tool %s not yet implemented (NotImplementedError)", fn_name)
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: finish_reply(
                    kind="needs_owner",
                    text="This feature isn't available yet. The owner has been notified.",
                    input_id=input_id,
                    session_id=session_id,
                    business_id=business_id,
                ),
            )
            return
        except Exception:
            log.exception("Tool %s raised an unexpected error", fn_name)
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: finish_reply(
                    kind="needs_owner",
                    text="Something went wrong. Please try again or contact the store.",
                    input_id=input_id,
                    session_id=session_id,
                    business_id=business_id,
                ),
            )
            return

        if is_terminal:
            log.info(
                "Terminal tool %s completed for input_id=%s — loop ends",
                fn_name, input_id,
            )
            return

        # ── Feed tool result back to model for next turn ──────────────────────
        # Append the model's function call + the tool response to contents
        model_turn_parts = [{"functionCall": {"name": fn_name, "args": fn_args}}]
        tool_response_parts = [
            {
                "functionResponse": {
                    "name": fn_name,
                    "response": {"content": tool_result},
                }
            }
        ]
        contents = contents + [
            {"role": "model", "parts": model_turn_parts},
            {"role": "user",  "parts": tool_response_parts},
        ]

    # ── MAX_TOOL_TURNS reached without a terminal action ──────────────────────
    log.warning(
        "MAX_TOOL_TURNS (%d) reached for input_id=%s without terminal — "
        "persisting needs_owner",
        MAX_TOOL_TURNS, input_id,
    )
    await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: finish_reply(
            kind="needs_owner",
            text=(
                "I couldn't complete your request in time. "
                "Please try rephrasing or contact the store directly."
            ),
            input_id=input_id,
            session_id=session_id,
            business_id=business_id,
        ),
    )
