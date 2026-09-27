"""
FastAPI entrypoint. Wires together the webhook, auth, bot_link, owner page,
and evidence panel routers, starts the sender loop, dispatcher worker,
and the startup recovery pass (Section H), and exposes the health-check endpoint (Section C).

This file stays thin -- routing and startup/shutdown wiring only.
Business logic belongs in transactions.py / holds.py / tools/.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.auth import router as auth_router
from app.bot_link import router as bot_link_router
from app.db import close_pool, health_ping, init_pool
from app.dispatcher import dispatch_pending, start_dispatcher_loop
from app.recovery import requeue_interrupted
from app.sender import start_sender_loop
from app.webhook import router as webhook_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    log.info("EmberGround starting up")
    init_pool()
    requeue_interrupted()
    await start_sender_loop()
    await start_dispatcher_loop()
    # Re-dispatch any rows that were requeued by recovery
    await dispatch_pending()
    log.info("EmberGround ready")
    yield
    # --- Shutdown ---
    close_pool()
    log.info("EmberGround shut down")


app = FastAPI(title="EmberGround", lifespan=lifespan)

# Register routers
app.include_router(webhook_router)
app.include_router(auth_router)
app.include_router(bot_link_router)

# Owner page and evidence panel routers are wired in later blocks:
# from app.owner_page.routes import router as owner_router
# from app.evidence_panel.routes import router as evidence_router
# app.include_router(owner_router)
# app.include_router(evidence_router)


@app.get("/health")
async def health():
    """External DB-touching health check — Section C says run every ~3 min
    to mitigate idle sleep on Render."""
    ok = health_ping()
    if ok:
        return {"status": "ok"}
    return JSONResponse(status_code=503, content={"status": "error", "message": "Database ping failed"})
