"""
verify_gemini_models.py — Shahana's Gemini model screening tool
================================================================
Run: python scratch/verify_gemini_models.py

What it does:
  1. Reads GEMINI_API_KEY from .env (via python-dotenv).
  2. Lists every model available to your key via the REST /models endpoint.
  3. Filters to models that support generateContent + function-calling.
  4. Fires a REAL function-calling test call against each candidate using a
     trivial dummy tool (get_stock), in priority order.
  5. Prints a ranked results table.
  6. Writes the recommended MODEL_NAME and MODEL_FALLBACK_NAME to stdout in
     a format you can paste directly into your .env file.

Requirements: pip install google-genai python-dotenv requests
"""

import os
import sys
import json
import time
import requests
from dotenv import load_dotenv

# ── Load key ─────────────────────────────────────────────────────────────────
load_dotenv()  # reads .env in cwd (run from project root)
API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

if not API_KEY or API_KEY in ("your_gemini_api_key_here", ""):
    print("ERROR  GEMINI_API_KEY is not set in your .env file.")
    print("    Add it: GEMINI_API_KEY=<your actual key>")
    sys.exit(1)

print(f"OK  Key loaded (last 6 chars: ...{API_KEY[-6:]})\n")

# ── Candidate models to test, in preference order ────────────────────────────
# Updated from the LIVE model list returned by this key (Sept 2026).
# Old 1.5/2.0-era names are NOT on this key -- use the names exactly as
# returned by the /models endpoint above.
CANDIDATE_PRIORITY_ORDER = [
    "gemini-3.5-flash",           # Primary candidate: fast, strong FC support
    "gemini-3.5-flash-lite",      # User-requested: lightweight, lower cost
    "gemini-3.6-flash",           # Next-gen flash tier
    "gemini-3.7-flash",           # Newer flash tier
    "gemini-3.8-flash",           # Latest flash tier
    "gemini-2.5-flash",           # Proven stable fallback
    "gemini-2.5-flash-lite",      # Lean fallback
    "gemini-2.5-pro",             # High-capability fallback
    "gemini-flash-latest",        # Alias — resolves to current flash
    "gemini-flash-lite-latest",   # Alias — resolves to current flash-lite
    "gemini-pro-latest",          # Alias — resolves to current pro
    "gemini-3.1-flash-lite",      # Preview tier option
    "gemini-3.1-flash-lite-preview",
]

# ── Step 1: List models your key can actually see ────────────────────────────
print("=" * 64)
print("STEP 1 -- Fetching model list from Generative Language API...")
print("=" * 64)

LIST_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models"
    f"?key={API_KEY}&pageSize=100"
)
try:
    r = requests.get(LIST_URL, timeout=15)
    r.raise_for_status()
    all_models = r.json().get("models", [])
except Exception as e:
    print(f"ERROR  Failed to list models: {e}")
    sys.exit(1)

# Filter: must support generateContent
generatable = [
    m for m in all_models
    if "generateContent" in m.get("supportedGenerationMethods", [])
]

print(f"  Total models returned:             {len(all_models)}")
print(f"  Models supporting generateContent: {len(generatable)}")
print()

# Show full list
print("  All generateContent-capable models:")
for m in generatable:
    name = m["name"].replace("models/", "")
    print(f"    - {name}")
print()

# ── Step 2: Live function-calling test ───────────────────────────────────────
print("=" * 64)
print("STEP 2 -- Function-calling smoke test (real API call per model)")
print("=" * 64)
print()

# Trivial dummy tool -- same pattern as the real find_options
DUMMY_TOOL_SCHEMA = {
    "function_declarations": [
        {
            "name": "get_stock",
            "description": "Returns current stock for a given SKU.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "sku": {
                        "type": "STRING",
                        "description": "The stock-keeping unit identifier."
                    }
                },
                "required": ["sku"]
            }
        }
    ]
}

DUMMY_USER_MESSAGE = "How many units of SKU ABC-001 do we have in stock?"


def test_model_function_calling(model_short_name: str) -> dict:
    """
    Fires a real generateContent call with tools against the given model.
    Returns a result dict with keys: ok, latency_ms, called_fn, error.
    """
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model_short_name}:generateContent?key={API_KEY}"
    )
    payload = {
        "contents": [{"role": "user", "parts": [{"text": DUMMY_USER_MESSAGE}]}],
        "tools": [DUMMY_TOOL_SCHEMA],
        "tool_config": {"function_calling_config": {"mode": "AUTO"}},
    }
    t0 = time.time()
    try:
        resp = requests.post(url, json=payload, timeout=30)
        latency_ms = int((time.time() - t0) * 1000)
        if resp.status_code == 404:
            return {"ok": False, "latency_ms": latency_ms, "called_fn": None,
                    "error": "404 -- model not found under this key"}
        if resp.status_code == 429:
            return {"ok": False, "latency_ms": latency_ms, "called_fn": None,
                    "error": "429 -- rate limit / quota exceeded"}
        if resp.status_code not in (200, 201):
            body = resp.text[:200]
            return {"ok": False, "latency_ms": latency_ms, "called_fn": None,
                    "error": f"HTTP {resp.status_code}: {body}"}

        data = resp.json()
        # Check if model actually returned a function call
        candidates = data.get("candidates", [])
        if not candidates:
            return {"ok": False, "latency_ms": latency_ms, "called_fn": None,
                    "error": "No candidates in response"}

        parts = candidates[0].get("content", {}).get("parts", [])
        fn_call = next(
            (p.get("functionCall") for p in parts if "functionCall" in p), None
        )

        if fn_call:
            return {"ok": True, "latency_ms": latency_ms,
                    "called_fn": fn_call.get("name"), "error": None}
        else:
            # Model replied in text instead of calling the function
            text_reply = " ".join(
                p.get("text", "") for p in parts if "text" in p
            )[:80]
            return {"ok": False, "latency_ms": latency_ms, "called_fn": None,
                    "error": f"No fn_call returned -- text reply: '{text_reply}'"}

    except requests.exceptions.Timeout:
        return {"ok": False, "latency_ms": 30000, "called_fn": None,
                "error": "Timeout (30s)"}
    except Exception as exc:
        return {"ok": False, "latency_ms": 0, "called_fn": None,
                "error": str(exc)}


results = []
available_names = {m["name"].replace("models/", "") for m in generatable}

for model in CANDIDATE_PRIORITY_ORDER:
    in_list = model in available_names
    print(f"  Testing: {model:<42} ", end="", flush=True)

    if not in_list:
        print("SKIP (not in your model list)")
        results.append({"model": model, "ok": False, "in_list": False,
                        "latency_ms": None, "called_fn": None,
                        "error": "Not in model list for this key"})
        continue

    result = test_model_function_calling(model)
    result["model"] = model
    result["in_list"] = True
    results.append(result)

    if result["ok"]:
        print(f"PASS  fn_call={result['called_fn']}  latency={result['latency_ms']}ms")
    else:
        print(f"FAIL  {result['error']}")

    time.sleep(0.5)  # gentle rate-limit buffer between calls

# ── Step 3: Summary table + .env recommendation ──────────────────────────────
print()
print("=" * 64)
print("STEP 3 -- Results Summary")
print("=" * 64)
print()
print(f"  {'Model':<44} {'In List':<9} {'FC Pass':<9} Latency")
print(f"  {'-'*44} {'-'*8} {'-'*8} {'-'*10}")
for r in results:
    in_list = "YES" if r["in_list"] else "NO"
    fc = "PASS" if r["ok"] else "FAIL"
    lat = f"{r['latency_ms']}ms" if r["latency_ms"] is not None else "---"
    print(f"  {r['model']:<44} {in_list:<9} {fc:<9} {lat}")

print()

passing = [r for r in results if r["ok"]]

if not passing:
    print("ERROR  NO model passed function-calling test with this API key.")
    print("       Check your key permissions, quota, or project billing settings.")
    sys.exit(1)

primary = passing[0]["model"]
fallback = passing[1]["model"] if len(passing) > 1 else primary

print("=" * 64)
print("RECOMMENDATION -- paste these into your .env file:")
print("=" * 64)
print()
print(f"GEMINI_MODEL={primary}")
print(f"MODEL_NAME={primary}")
print(f"MODEL_FALLBACK_NAME={fallback}")
print()
print(f"Primary  : {primary}  (latency: {passing[0]['latency_ms']}ms)")
if len(passing) > 1:
    print(f"Fallback : {fallback}  (latency: {passing[1]['latency_ms']}ms)")
else:
    print(f"Fallback : {fallback}  (same -- only one model passed)")
print()
print("Record these in your .env NOW before implementing run_agent_turn.")
