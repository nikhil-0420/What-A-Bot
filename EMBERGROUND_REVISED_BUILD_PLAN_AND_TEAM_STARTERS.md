# EmberGround — Revised Build Plan & Team Starter Package
**Generated 1:00 PM IST, 27 Sept 2026 · Deadline 5:30 PM IST · 4.5 hours remaining**

Baseline confirmed by direct code inspection (not just self-report): `app/webhook.py`, `app/dispatcher.py`, `app/transactions.py`, `app/sender.py`, `app/recovery.py`, `app/config.py`, `app/db.py` are real, working Telegram echo plumbing — confirmed live. `app/model_agent.py`, every file in `app/tools/`, and `app/holds.py` are 100% `raise NotImplementedError` — zero agent/order logic exists yet. `tests/test_verification_checklist.py` is all `pass` stubs; `tests/test_language_cases.py`'s test function is `raise NotImplementedError`. These are the honest starting line — none of this is a criticism of last night's work, it's exactly where a proven block-1 checkpoint should leave you.

---

## A. Decisions and Feasibility

**Product:** A multi-business AI ordering/booking assistant for small Indian businesses, demoed as a retailer-facing web dashboard (login → pick your business → link your Telegram bot) with the actual customer conversation happening in Telegram.

**Track:** **The Agentic Business** — justified by the actual build: an agent that reads real inventory/slots, proposes a validated basket or booking, and only commits after explicit confirmation, across three distinct verticals. Not "Fix a Broken Workflow" (too narrow a framing for what's built), not "Beyond the Screen" (this *is* a screen-plus-chat product).

**Three demo flows:**
1. Stationery (flagship): Hinglish budget-constrained notebook order → agent proposes basket → confirm → invoice.
2. Supermarket: fixed small packaged-goods catalog → simple quantity order → confirm.
3. Service booking (fictional "UrbanFix-style home services demo," no real company affiliation claimed): pick a service → agent shows available slots → confirm → one capacity unit allocated atomically.

**Feature matrix — priority is real, not decorative. P0 gates the submission. P1 is a real goal but expendable. P2 is cut first if the clock forces it.**

| Feature | Owner | Depends on | Acceptance condition | Priority |
|---|---|---|---|---|
| Auth + business picker + bot-link token | Nikhil (backend) + Ashraf (frontend) | contract freeze | Owner logs in, sees only their businesses, generates a working `/start <token>` deep link | P0 |
| Retail engine (stationery + supermarket) | Sam | schema freeze | Real `find_options`→`propose_order`→`confirm_order`, CAS-safe, both businesses | P0 |
| Gemini agent loop | Shahana | tool contracts frozen | Model calls the right tool with correct args on all 8 language cases | P0 |
| Breeth memory | Shahana, access chased by Nikhil | Breeth API key | One real store + one real retrieve, shown in evidence view | P0 (event-required, not optional) |
| Dispatcher/auth/tenant bug fixes (§3 known issues) | Nikhil | none | See fix list below | P0 |
| Owner ops pages (stock/holds/evidence) | Jagdeog... **Jagdeep** | Ashraf's shared primitives | Owner can see and act on real DB state | P0 |
| Service booking | Sam (extends retail's transaction boundary) | retail P0 done | One real booking, capacity decrements atomically | P1 |
| ElevenLabs voice | Shahana | Gemini loop stable | One real voice note → transcript → quote, shown honestly | P1 |
| n8n notification | Nikhil | retail P0 done | One real hold triggers one real Telegram ping to an owner chat | P1 |
| Dodo software billing | Jagdeep | none (fully isolated) | One real test-mode checkout, webhook reconciled, **never touches order/booking state** | P2 |
| Proxy study | whoever has slack at 4:15 | all P0/P1 done | 3 real people or explicitly labelled self-test | P2 |
| Additional multilingual voice beyond Hinglish | — | — | explicitly optional, do not attempt unless everything above is done | P2, likely cut |

**Honest risk flags, not hidden:** Breeth access is unconfirmed as of 1:00 PM — this blocks a *required* event feature, not an optional one. Dodo's own policy excludes physical-goods/in-person-service payment, so it's implemented as retailer *software billing*, never customer payment — say this explicitly in the demo, don't let it look like checkout for notebooks. If Breeth access isn't confirmed by 1:30 PM, escalate immediately (see §J).

---

## B. Architecture and Data Flows

```
Retailer (browser)                         Customer (Telegram)
  → login (email/password, seeded)           → /start <token>  (binds chat to business_id)
  → GET /businesses (own memberships)         → types/speaks an order or booking request
  → pick business                             ↓
  → POST bot-link → gets deep link          Telegram webhook (existing, proven)
  → opens Telegram, /start <token>            → inbox row (tenant resolved from bound chat,
  → owner ops pages (stock/holds/evidence)      NEVER from a global mutable "current business")
                                               → dispatcher → Gemini agent loop (NEW)
                                                    → find_options / propose_order / confirm_order
                                                      / book_slot / answer_faq / finish_reply
                                                    → Breeth: read business FAQ/customer prefs
                                                      (untrusted context, never overrides
                                                      explicit current constraints)
                                               → run_terminal_action (existing, proven pattern)
                                                    → business effect + message_outcomes + outbox
                                               → sender (existing, proven) → real Telegram reply

Held order → commit → AFTER commit → n8n → owner's Telegram chat (notification only, no callback)
Retailer billing → Dodo hosted checkout → webhook → business_plan row (never touches orders/bookings)
```

**Server-side tenant identity, everywhere:** `business_id` is resolved once, at bind time (`/start <token>` consumes the token and writes `chat_id → business_id` into `sessions`), and every subsequent inbox row for that chat inherits it from the stored session — never from request context, never re-resolved per message. A browser business switch only affects a *new* link/token; it can never retarget an already-queued or already-bound chat.

**Minimal persisted conversation state:** the existing `sessions` + `inbox` + `orders`/`bookings` tables already carry this — the open quote/booking *is* the conversation state for corrections. No new conversation-memory table needed; Breeth is external, supplementary, and never authoritative.

---

## C. File Tree, Ownership, Contracts

Frontend: **React + Vite + TypeScript** (no existing convention to preserve — greenfield). Minimal styling (plain CSS or Tailwind utility classes only, no component library to save setup time).

```
emberground/
  app/
    config.py                    [Nikhil]  — add owner/session/JWT config, Dodo/n8n keys
    db.py                        [Nikhil]  — unchanged pattern, verify pool close-on-shutdown fix
    main.py                      [Nikhil]  — fix pool-by-value import bug, register all routers
    webhook.py                   [Nikhil]  — fix input_id scheme (see §3 fix list)
    dispatcher.py                [Nikhil]  — add supervised due-inbox worker (see §3 fix list)
    transactions.py              [Sam]     — add session/business validation in run_terminal_action
    sender.py                    [Nikhil]  — fix silent-ok-false bug, redact tokens in logs
    recovery.py                  [Nikhil]  — unchanged
    model_agent.py                [Shahana] — implement real agent loop
    holds.py                     [Sam]     — implement (reuses her transaction work)
    tools/
      find_options.py            [Sam]
      propose_order.py           [Sam]
      confirm_order.py           [Sam]
      book_slot.py       (NEW)   [Sam]
      answer_faq.py               [Shahana] — wires Breeth
      finish_reply.py            [Shahana]
    memory/breeth_adapter.py (NEW) [Shahana]
    auth.py (NEW)                 [Nikhil]  — login/session/JWT, owner membership checks
    bot_link.py (NEW)             [Nikhil]  — token issue/consume
    n8n.py (NEW)                  [Nikhil]
    billing/dodo.py (NEW)         [Jagdeep] — checkout + webhook, fully isolated
    owner_page/routes.py         [Jagdeep]
    evidence_panel/routes.py     [Jagdeep]
  migrations/
    001_init.sql                 (existing, unchanged)
    002_multi_business.sql (NEW) [Nikhil — sole migration owner, see §D]
  frontend/ (NEW)
    src/
      api/client.ts               [Ashraf]  — shared, others consume, don't edit
      pages/Login.tsx             [Ashraf]
      pages/BusinessPicker.tsx    [Ashraf]
      pages/BotLink.tsx           [Ashraf]
      components/ (shared UI)      [Ashraf]
      pages/Stock.tsx             [Jagdeep]
      pages/Holds.tsx             [Jagdeep]
      pages/Evidence.tsx          [Jagdeep]
      pages/Billing.tsx           [Jagdeep]
  docs/
    CONTRACTS.md (NEW)            [Nikhil, authoritative, frozen after §C.1]
    OWNERSHIP.md (NEW)            [Nikhil]
    INTEGRATION_CHECKLIST.md (NEW)[Nikhil]
    DEMO_RUNBOOK.md (NEW)         [Nikhil]
  AGENTS.md (NEW)                 [Nikhil]
  prompts/ (NEW, the 5 files in §G below)
```

**No one but Nikhil edits:** `main.py` router registration, `db.py`, `config.py`, any migration file, `docs/CONTRACTS.md`. Everyone else's changes to shared types/schema go through Nikhil as a small PR against those files, not direct edits.

### C.1 — Frozen API Contract (freeze at 1:15 PM, changes after that go through Nikhil)

| Route | Method | Auth | Request | Response | Notes |
|---|---|---|---|---|---|
| `/auth/login` | POST | none | `{email, password}` | `{token}` or 401 | seeded owner accounts |
| `/auth/me` | GET | Bearer | — | `{owner_id, email, businesses: [business_id]}` | |
| `/businesses` | GET | Bearer | — | `[{business_id, name, business_type}]` | only owner's memberships |
| `/businesses/{id}/bot-link` | POST | Bearer, must own `{id}` | — | `{token, deep_link_url, expires_at}` | single-use, 10 min expiry |
| `/businesses/{id}/catalog` | GET | Bearer | — | `[{sku, name, brand, ruling, size, price_paise, qty}]` | retail only |
| `/businesses/{id}/services` | GET | Bearer | — | `[{service_id, name, duration_minutes, price_paise}]` | service only |
| `/businesses/{id}/slots` | GET | Bearer | `?service_id=` | `[{slot_id, starts_at, capacity}]` | |
| `/businesses/{id}/orders` | GET | Bearer | `?status=` | `[{order_id, status, total_paise, ...}]` | read-only, confirmation stays a Telegram action |
| `/businesses/{id}/holds` | GET/POST | Bearer | POST: `{order_id, approve: bool}` | order/booking row | owner approve/reject |
| `/businesses/{id}/evidence` | GET | Bearer | — | trace + latency/cost fields | never claimed private reasoning |
| `/businesses/{id}/billing/checkout` | POST | Bearer | — | `{checkout_url}` | Dodo hosted checkout |
| `/businesses/{id}/billing/status` | GET | Bearer | — | `{plan, updated_at}` | |
| `/webhook/telegram` | POST | secret header | Telegram Update | 200 | existing, unchanged |
| `/webhook/dodo` | POST | signature | Dodo event | 200 | new, isolated, never touches orders/bookings |

**Error envelope, all routes:** `{"error": {"code": str, "message": str}}`, matching HTTP status. Money: integer paise everywhere, same as existing convention. Timestamps: stored/transmitted UTC ISO-8601; displayed in Asia/Kolkata on frontend only.

---

## D. Migration 002 — Executable, Additive, Nikhil-Owned

```sql
-- migrations/002_multi_business.sql
-- Additive only. Does not touch 001_init.sql's tables/rows. Apply once, after
-- reviewing against the actual current schema (IDE agent: verify column names
-- against the real 001_init.sql before running — this is drafted against the
-- version described in the master prompt, may have drifted).

ALTER TABLE businesses ADD COLUMN business_type TEXT NOT NULL DEFAULT 'retail'
    CHECK (business_type IN ('retail', 'service'));

ALTER TABLE inbox ADD COLUMN telegram_chat_id BIGINT;
ALTER TABLE inbox ADD COLUMN telegram_update_id BIGINT;
ALTER TABLE inbox ADD COLUMN telegram_message_id BIGINT;
-- Fixes known issue #1: input_id becomes 'tg:<bot_id>:<update_id>' (globally
-- unique, not chat-scoped message_id). Store chat/message id separately for tracing.

CREATE TABLE owners (
    owner_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE owner_business_memberships (
    owner_id UUID NOT NULL REFERENCES owners(owner_id),
    business_id TEXT NOT NULL REFERENCES businesses(business_id),
    PRIMARY KEY (owner_id, business_id)
);

CREATE TABLE bot_link_tokens (
    token TEXT PRIMARY KEY,
    business_id TEXT NOT NULL REFERENCES businesses(business_id),
    owner_id UUID NOT NULL REFERENCES owners(owner_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    consumed_by_chat_id BIGINT
);
-- Single-use: consumed_at IS NULL is the only usable state. Enforce in code
-- via UPDATE ... WHERE consumed_at IS NULL RETURNING token (CAS pattern,
-- same style as order confirmation).

CREATE TABLE services (
    business_id TEXT NOT NULL REFERENCES businesses(business_id),
    service_id TEXT NOT NULL,
    name TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL CHECK (duration_minutes > 0),
    price_paise INTEGER NOT NULL CHECK (price_paise > 0),
    PRIMARY KEY (business_id, service_id)
);

CREATE TABLE service_slots (
    slot_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id TEXT NOT NULL,
    service_id TEXT NOT NULL,
    starts_at TIMESTAMPTZ NOT NULL,
    capacity INTEGER NOT NULL CHECK (capacity >= 0),
    FOREIGN KEY (business_id, service_id) REFERENCES services(business_id, service_id)
);

CREATE TABLE bookings (
    booking_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    origin_input_id TEXT UNIQUE NOT NULL REFERENCES inbox(input_id),
    session_id UUID NOT NULL REFERENCES sessions(session_id),
    business_id TEXT NOT NULL REFERENCES businesses(business_id),
    slot_id UUID NOT NULL REFERENCES service_slots(slot_id),
    status TEXT NOT NULL CHECK (status IN ('draft', 'held', 'confirmed', 'cancelled')),
    total_paise INTEGER NOT NULL CHECK (total_paise >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Capacity allocation on confirm: same CAS-then-decrement pattern as stock,
-- against service_slots.capacity, inside run_terminal_action.

CREATE TABLE billing_events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id TEXT NOT NULL REFERENCES businesses(business_id),
    dodo_event_id TEXT UNIQUE NOT NULL,   -- dedup key
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE business_plan (
    business_id TEXT PRIMARY KEY REFERENCES businesses(business_id),
    plan TEXT NOT NULL DEFAULT 'trial' CHECK (plan IN ('trial', 'test_paid')),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**Seed data (Nikhil runs once, idempotent — `INSERT ... ON CONFLICT DO NOTHING`, never a destructive reset on normal startup):**
- `businesses`: `demo-stationery-1` (retail, existing fixture A/B/C/D unchanged), `demo-supermarket-1` (retail, ~6 packaged SKUs, integer package counts), `demo-services-1` (service, "UrbanFix-style home services demo", 2–3 services, a handful of slots today/tomorrow).
- `owners`: at least 2 seeded accounts — one with membership to all three businesses (for the main demo), one restricted to a single business (to prove isolation, per master prompt §"Demo authentication").
- Stable, hardcoded IDs everywhere above — never regenerated per run.
- A separate, explicit `scripts/demo_reset.py` (dev-only, never called on startup) if a reset is needed mid-afternoon.

---

## E. Five-Person Timeline (1:00 PM → 5:30 PM)

| Time | Nikhil | Sam | Shahana | Ashraf | Jagdeep |
|---|---|---|---|---|---|
| 1:00–1:15 | Run Antigravity scaffold prompt (§F). Start Breeth access chase in parallel. | Read CONTRACTS.md draft | Read CONTRACTS.md draft | Read CONTRACTS.md draft | Read CONTRACTS.md draft |
| 1:15 | **Contract freeze** — publish CONTRACTS.md, no more schema/route changes without going through Nikhil | | | | |
| 1:15–3:00 | Bug fixes §3, auth.py, bot_link.py, n8n.py (build against contract) | Retail engine: schema-verified tools, transactions, CAS | Gemini agent loop + Breeth adapter (mocked until key lands) | Login/picker/bot-link UI against mocked API client | Owner ops pages against mocked API client |
| **3:00** | **GATE 1 — first integrated vertical slice.** Real Telegram → real Gemini → real DB, stationery only. If this slips, P1 items are cut now, not discovered later. | | | | |
| 3:00–4:15 | Integrate PRs, wire n8n, keep chasing Breeth if still blocked | Extend to booking (P1) | ElevenLabs voice (P1) once loop is stable | Replace mocks with real API calls, add supermarket picker | Real data wired in, evidence view, billing UI shell |
| **4:15** | **GATE 2 — all-domain gate.** All 3 businesses minimally demoable, one memory effect shown, one notification shown. | | | | |
| 4:15–4:45 | **Feature freeze.** Bug fixes only. | bug fixes | bug fixes | bug fixes | Dodo (P2, only if everything above is green) |
| 4:45–5:10 | Record 2-min demo video, assemble evidence/runbook | available to help record | available | available | available |
| 5:10–5:30 | GitHub hygiene, submission, final check | | | | |

**Critical path:** Sam's retail engine and Shahana's Gemini loop are both on the critical path and depend on each other's tool contracts, not each other's code — that's why the contract freeze at 1:15 matters more than anything else today. **Overload risk:** Shahana was originally slated for 4 sponsor integrations; this plan reduces her to Gemini + Breeth (both P0) with ElevenLabs as P1 only after the loop works — n8n and Dodo moved off her plate entirely, onto Nikhil and Jagdeep respectively, exactly as the master prompt itself warned was necessary.

**Merge discipline:** small PRs against `main` as each piece lands (tool-by-tool, page-by-page), not five branches merged at 5:00. Nikhil reviews anything touching a shared file; everything else can merge on its owner's own say-so once it passes its own smoke check.

---

## F. Antigravity Scaffolding Prompt (copy-paste, run once, Nikhil only)

```
Inspect the current repository (app/, tests/, scratch/) before changing anything.
Report the actual baseline: which files have real logic vs. raise NotImplementedError,
and confirm app/webhook.py, dispatcher.py, transactions.py, sender.py, recovery.py
are the proven, working Telegram pipeline — do not touch their working behavior.

Create a git branch/checkpoint before making changes.

Then:
1. Create migrations/002_multi_business.sql with the exact schema from the plan
   I'm pasting below (Section D) — verify it against the REAL current
   001_init.sql column names first, adjust if anything has drifted, tell me
   what you changed.
2. Create these new backend files as import-clean skeletons (TODO + raise
   NotImplementedError bodies, exact signatures from Section C.1's contract
   table and Section D's schema — no invented fields):
   app/auth.py, app/bot_link.py, app/n8n.py, app/memory/breeth_adapter.py,
   app/billing/dodo.py, app/tools/book_slot.py
3. Scaffold a new frontend/ directory: React + Vite + TypeScript, minimal
   dependencies (no component library), with empty page files at the paths
   in Section C's file tree, a shared src/api/client.ts with typed fetch
   wrappers matching Section C.1's routes exactly, and mock data clearly
   labeled MOCK and confined to import.meta.env.DEV.
4. Keep the FastAPI app importable and the Vite app runnable after every
   change — verify both with an import check / `npm run build` after
   scaffolding, not just at the end.
5. Any not-yet-implemented backend endpoint must return a real HTTP
   501/503 with a clear message — never a fake 200 success.
6. Create docs/CONTRACTS.md (the exact content of Sections C and C.1 below),
   docs/OWNERSHIP.md (the file tree with owners from Section C),
   docs/INTEGRATION_CHECKLIST.md (Section H below), docs/DEMO_RUNBOOK.md
   (Section I below), and a root AGENTS.md stating: five people are working
   in this repo concurrently, each owns specific files listed in
   OWNERSHIP.md, no one edits another owner's files without a PR reviewed
   by Nikhil, CONTRACTS.md is frozen and authoritative after 1:15 PM today.
7. Add real placeholders (not fake values) to .env.example for:
   JWT_SECRET, GEMINI_API_KEY, GEMINI_MODEL, ELEVENLABS_API_KEY,
   BREETH_API_KEY, N8N_WEBHOOK_URL, N8N_SHARED_SECRET, DODO_API_KEY,
   DODO_WEBHOOK_SECRET — never put real keys in any committed file.
8. Do NOT run the migration against the live database, do not touch any
   external account, do not modify the existing Telegram webhook behavior.
   That's each task owner's job once they start.

Report file-by-file what you created, what you verified (actual import/build
output, not a summary), and stop — do not implement business logic, that's
the five starter prompts' job.
```

---

## G. Five IDE Starter Prompts

Each teammate pastes their own into their own Antigravity IDE, after Nikhil's scaffold (§F) has run and `docs/CONTRACTS.md` exists.

### G.1 — Nikhil

```
Role: team lead — bootstrap, auth, tenant integrity, integration.
Baseline: Telegram echo pipeline is proven working. Your job today is NOT
new product features — it's making the foundation trustworthy for four
people to build on top of, plus the pieces only you should own.

Read first: docs/CONTRACTS.md, docs/OWNERSHIP.md, app/webhook.py,
app/dispatcher.py, app/transactions.py, app/sender.py.

You own, no one else edits: app/main.py, app/config.py, app/db.py,
migrations/*, app/webhook.py, app/dispatcher.py, app/sender.py, app/auth.py,
app/bot_link.py, app/n8n.py, docs/CONTRACTS.md.

Fix these known issues first, in order:
1. webhook.py: input_id must be 'tg:<bot_id>:<update_id>' (globally unique),
   not chat-scoped message_id. Store telegram_chat_id/update_id/message_id
   separately (migration 002 adds these columns). On a duplicate update_id,
   load the ALREADY-persisted tenant/session and dispatch only the accepted
   row — never trust new request context for an existing ID.
2. dispatcher.py: add a supervised background worker that polls due rows
   respecting next_attempt_at, not just a startup-only pass. Define and
   implement what happens after a row exhausts retries into 'attention' —
   it must stay visible on the owner page, never silently stuck.
3. Remove the hardcoded test_shop tenant assignment in webhook.py. Tenant
   comes from sessions.active_business_id, set once when a bot_link_tokens
   row is consumed via /start <token> — never reset per message, never a
   global mutable value.
4. transactions.py's run_terminal_action currently locks only by input_id.
   Hand off to Sam: it must also validate the supplied session_id/
   business_id against the locked row, not just trust them. Flag this to
   her directly, don't fix her file yourself.
5. sender.py: check the actual 'ok' field in Telegram's JSON response, not
   just HTTP 200/201 — mark ambiguous/failed sends correctly, never
   'accepted' on a false ok. Redact the bot token from any logged URL.
6. main.py: fix the pool-imported-by-value issue so shutdown actually
   closes the real pool. Health endpoint returns real 503 on DB failure,
   not a 200 with a failure tuple inside it.

Then build: app/auth.py (login/me, JWT or signed session cookie — your
call, keep it simple, document CSRF handling if you use cookies),
app/bot_link.py (issue via CAS-style single-use token, consume via /start
<token> handler wired into webhook.py), app/n8n.py (one held-order →
one Telegram notification to a separate owner bot/chat — never register
a second webhook on the customer-facing bot).

Run the Breeth access verification RIGHT NOW, in parallel with all of the
above — it's a required event feature and Shahana is blocked without it.
Report back to me (Claude) within 30 minutes whether it's resolved.

Integration duty: review and merge PRs touching shared files throughout
the afternoon — protect your own time for this, don't let bug-fixing
consume all of it.

Test/build: `pytest`, confirm `uvicorn app.main:app` still boots after
every change. Commit small, push often.
```

### G.2 — Sam

```
Role: retail + booking transactions — the safety-critical core.
Baseline: app/transactions.py has a proven run_terminal_action pattern
(lock inbox → check message_outcomes → business action → outcome/outbox/
complete, all one transaction) — reuse it, don't reinvent it.

Read first: docs/CONTRACTS.md, migrations/001_init.sql,
migrations/002_multi_business.sql, app/transactions.py,
app/tools/find_options.py, app/tools/propose_order.py,
app/tools/confirm_order.py.

You own: app/transactions.py, app/holds.py, app/tools/find_options.py,
app/tools/propose_order.py, app/tools/confirm_order.py,
app/tools/book_slot.py (once you reach it).

Tasks, in order:
1. Add session/business validation inside run_terminal_action — it
   currently only locks by input_id. Verify the locked inbox row's
   session_id/business_id match what's supplied, reject mismatches.
2. Implement find_options/propose_order/confirm_order for BOTH retail
   businesses (stationery: full ruling/size/budget/brand constraints per
   the original fixture; supermarket: simpler integer-quantity-only,
   no ruling/size). Reuse one retail engine, branch on business_type only
   where genuinely needed.
3. propose_order MUST enforce: sum of selected quantities equals requested
   quantity, budget, current stock, current price, size/ruling/brand
   permission where relevant — resolved server-side from the stored
   candidate_set_id, never from the model's restated constraints.
4. confirm_order: CAS on status, deterministic stock decrement in sorted
   SKU order, rollback whole transaction on any partial failure, structured
   stale-quote result on stock/price mismatch.
5. holds.py: implement draft→held transition (same transaction pattern,
   no stock deducted, no invoice), owner_resolve_hold (same CAS pattern,
   expected_status='held', idempotent on repeat).
6. Once retail is solid and gate 1 passes: book_slot.py — same pattern,
   CAS against service_slots.capacity instead of catalog.qty.

Test with the existing fixture (A=5/4/3 stock scenarios,
tests/fixtures/catalog.json) before moving to supermarket data.

Acceptance: two confirmations of one order → one invoice, one stock
deduction. Two orders competing for stock → stock never negative, loser
gets a clean stale-quote reply, not a partial invoice.

If Nikhil's auth/tenant work isn't ready when you need session_id/
business_id — use the mock values in docs/CONTRACTS.md, don't block.

Test/build: pytest tests/test_verification_checklist.py — replace the
'pass' stubs relevant to your work with real assertions as you go, don't
leave them as false-positive no-ops.
```

### G.3 — Shahana

```
Role: Gemini agent loop + Breeth memory (both P0/required) + ElevenLabs
voice (P1, only once the loop is solid). n8n and Dodo are NOT yours —
Nikhil and Jagdeep own those, don't touch them.

Read first: docs/CONTRACTS.md, app/model_agent.py, app/tools/*.py
(signatures, once Sam/you have them stubbed), app/config.py.

You own: app/model_agent.py, app/tools/answer_faq.py,
app/tools/finish_reply.py, app/memory/breeth_adapter.py.

Tasks, in order:
1. Verify which Gemini model your actual API key/account can call with
   function-calling support RIGHT NOW — do not hardcode a model name from
   memory, confirm it with a real test call first. Pick one fallback.
   Record both in .env.
2. Implement run_agent_turn: give the model the tool schemas from
   app/tools/*.py (as they exist — coordinate with Sam if signatures
   aren't finalized yet, don't block, use CONTRACTS.md's frozen version),
   the catalog/services for business_id, and conversation so far. Execute
   whichever tool it calls. propose_order/confirm_order/book_slot are
   terminal — loop stops after a successful commit.
3. Bounded tool turns, provider timeout, bounded rate-limit retry. On
   quota failure: persist a truthful "please try again shortly" reply via
   finish_reply(kind='needs_owner'), never a fabricated result.
4. Breeth adapter: check the actual current docs/API access you have —
   if Nikhil hasn't confirmed a working key by 1:30 PM, implement the
   adapter interface now against the documented shape, mark it clearly
   BLOCKED in your status update, and swap in the real calls the moment
   the key lands. One real store + one real retrieve is the bar — a
   mocked Breeth path does NOT satisfy the event's required-sponsor rule,
   say so plainly if it stays blocked.
5. Memory is untrusted context, never authoritative — DB stock/price/
   confirmation status always win. Never carry one business's or
   customer's context into another's session.
6. Once the loop passes gate 1: ElevenLabs voice. Verify the actual
   supported Telegram voice-note format. Bounded download/transcription
   outside any DB transaction. On failure: ask the customer to type
   instead — never infer a confirmation from unclear audio; require the
   explicit confirm action after showing the quote either way.

Acceptance for the 8 language cases in tests/test_language_cases.py:
each produces the correct STORED outcome (message_outcomes row), not
just a plausible-looking reply.

Test/build: run the existing 8 cases against your live loop once wired,
report actual pass/fail per case, not a summary claim.
```

### G.4 — Ashraf

```
Role: frontend foundation everyone else builds on. Land this first —
Jagdeep is waiting on your shared client/primitives.

Read first: docs/CONTRACTS.md (Section C.1's route table is your
contract — don't invent fields not listed there).

You own: frontend/src/api/client.ts, frontend/src/pages/Login.tsx,
frontend/src/pages/BusinessPicker.tsx, frontend/src/pages/BotLink.tsx,
frontend/src/components/* (shared primitives). Jagdeep consumes these,
does not edit them — if he needs something new, he asks you.

Tasks, in order:
1. api/client.ts: typed fetch wrapper for every route in CONTRACTS.md
   Section C.1. Until Nikhil's auth.py is live, build against clearly
   labeled MOCK responses gated behind import.meta.env.DEV — never
   silently ship a mock as if it were real.
2. Login page → stores the token, redirects to business picker.
3. Business picker → GET /businesses, list only the owner's own
   memberships (test this with the restricted seeded account, not just
   the all-access one).
4. Bot-link page: POST /businesses/{id}/bot-link, show the deep link
   (Telegram t.me/<bot>?start=<token> format — verify the current
   Telegram deep-link constraints, don't assume the format from memory),
   a copy button, and honest instructions that the owner must actually
   click it and hit /start in Telegram — this is a required action, not
   automatic.
5. Shared primitives: a basic layout/nav shell, a loading/error state
   pattern, anything Jagdeep's pages will visibly need — check with him
   once before building extra.

Once real backend endpoints land (watch for Nikhil's/Sam's PRs), swap
your mocks for real calls — don't leave dead mock code in the DEV-only
path once it's replaced.

Acceptance: a fresh login → pick business → generate link → real
/start binds a real chat, testable by you sending /start yourself.

Test/build: `npm run build` must succeed after every change you land.
```

### G.5 — Jagdeep

```
Role: business operations UI (stock, holds, evidence, billing). Consume
Ashraf's client/primitives — don't edit his files, ask him if you need
something new there.

Read first: docs/CONTRACTS.md Section C.1, Ashraf's api/client.ts once
it exists.

You own: frontend/src/pages/Stock.tsx, Holds.tsx, Evidence.tsx,
Billing.tsx, and the isolated Dodo backend piece: app/billing/dodo.py,
the /webhook/dodo route.

Tasks, in order (P0 first, Dodo last and only if time allows):
1. Stock page: list current catalog/services per business, a manual
   stock-adjustment action (owner-only, audited via `events` — reuse the
   existing pattern, don't invent a new audit mechanism).
2. Holds page: list held orders/bookings, approve/reject buttons wired
   to POST /businesses/{id}/holds.
3. Evidence page: normalized constraints, candidate rows, validation
   result, order/booking status, stock/slot before-after, outbox state,
   latency/cost if available — real tool events, never claimed private
   reasoning. This page is what proves the demo isn't smoke and mirrors,
   treat it as important as any P0 feature even though it's "just a
   view."
4. Billing page (P1): shows current plan, a "test checkout" button →
   POST /businesses/{id}/billing/checkout → redirect to Dodo's hosted
   checkout. Label it clearly as retailer software billing, NOT customer
   payment for goods/services.
5. Dodo backend (P2, only after 1–4 are done and stable): verify your
   actual Dodo account's product/checkout-currency support before
   building against assumed fields. Preconfigure one software product.
   Webhook: verify signature, dedupe by dodo_event_id, update
   business_plan only — this must NEVER touch orders or bookings, treat
   that boundary as a hard rule, not a suggestion. Redirect success is
   display-only — the webhook's verified status is the only thing that
   changes entitlement.

If Dodo access/setup isn't working by 4:15 PM, drop it — say so plainly,
don't let it eat into feature-freeze time meant for bug fixes on P0/P1
work.

Test/build: `npm run build`; for dodo.py, pytest plus a real test-mode
webhook smoke call once credentials exist.
```

---

## H. Integration & Correctness Test Matrix

Original 11 checks (unchanged, still required) plus, new for this scope:

| New check | Required observation |
|---|---|
| Telegram cross-chat IDs / replays | Two different chats never share an inbox identity; a replayed update_id loads its original tenant, doesn't re-derive from new context |
| Ordered retry after 'attention' | A stuck row is visibly recoverable on owner page, not silently lost |
| Tenant switch with queued messages | An in-flight message keeps its original business_id even if the owner switches business in the browser meanwhile |
| Unauthorized business-picker access | Owner without membership gets 403, not an empty-but-technically-200 list |
| Expired / reused bot-link token | Both rejected, with a clear message, no silent no-op |
| Voice transcription failure | Customer gets "please type instead," not a stuck conversation |
| Cross-tenant memory leakage | Business A's Breeth context never appears in Business B's replies |
| Retail stock contention (both businesses) | Never negative, loser gets clean stale-quote |
| Service-slot contention | Same — capacity never negative |
| Stale quote after correction/price change | Rejected, new quote required |
| Duplicate/out-of-order Dodo events | Deduped by event ID, order-independent |
| Payment-return spoofing | Redirect alone changes nothing; only verified webhook status does |
| n8n failure | Held order still fully visible/actionable on owner page regardless |
| Gemini quota failure | Truthful "try again" reply persisted, never a fabricated result |
| Startup recovery | Unchanged from original — still required |

**Minimum release gate:** authorization (tenant isolation + owner membership), replay safety, invoice/booking correctness, stock/capacity never negative, billing integrity (never touches order state). Everything else is demo polish, not gate-blocking.

Test with mocked failure injection only where explicitly labeled as such — a live sponsor claim in the demo needs a live integration result behind it, not a mock standing in unlabeled.

---

## I. Demo, Evidence, Submission

**2-minute video storyboard:**
- 0:00–0:20 — problem framing, three-business scope stated honestly (flagship + two narrower demos)
- 0:20–1:10 — stationery flow: Hinglish request → real Telegram → real basket → confirm → invoice (the long-form proof)
- 1:10–1:35 — quick cuts: supermarket order confirmed, one booking confirmed, one memory effect shown in evidence view, one n8n notification shown arriving
- 1:35–1:50 — Dodo test billing shown as a short evidence cut, explicitly labeled software billing, only if it's actually working
- 1:50–2:00 — honest limitations + next step (merchant pilot)

Deterministic seed state before recording — don't record against data that's been mutated by afternoon testing. If any segment must be prerecorded due to timing, label it prerecorded explicitly; never blend into the live segments unlabeled.

**Submission package:** retailer demo runbook (docs/DEMO_RUNBOOK.md), readiness checklist against §H's release gate, measured latency/cost with genuine unknowns left unknown (don't backfill numbers), proxy/self-test notes if time allowed, the three required social posts (draft only — team posts, Claude doesn't publish), public GitHub repo with `.env` confirmed excluded, sponsor-use evidence tied to what's actually real in the recording.

---

## J. Sources, Open Blockers, Final Cross-Check

**Unverified, must be checked live, not assumed:** exact current Gemini model name/free-tier limits under your account, ElevenLabs' currently supported Telegram audio format, Breeth's actual API/MCP shape (docs were unreachable during prep — verify live or mark the adapter interface as best-effort), Dodo's actual currency/product support under your account, Telegram's current deep-link token constraints.

**Open blocker, escalate immediately:** Breeth API access. Nikhil chases this from 1:00 PM; if unresolved by 1:30 PM, escalate to a mentor/organizer — it's a required event feature, not a nice-to-have, and Shahana's whole afternoon depends on knowing which way this goes.

**Final consistency check before you call anything done:** every P0/P1 feature has exactly one owner · every shared file has exactly one owner · all five prompts agree on the same frozen contract · no external network call happens inside `run_terminal_action` · no customer payment is ever routed through Dodo · Breeth is either genuinely working or explicitly, visibly marked as a known gap in the evidence panel — never silently dropped · nothing in the demo or evidence panel claims a capability that wasn't actually tested today.
