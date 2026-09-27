"""
Neon pooled connection setup (Section C: "Neon pooled connection for short
transactions, no DB transaction held open during inference or approval").
"""
import contextlib
import logging

from psycopg_pool import ConnectionPool
from app.config import settings

log = logging.getLogger(__name__)

pool: ConnectionPool | None = None


def init_pool() -> None:
    global pool
    pool = ConnectionPool(
        settings.database_url,
        min_size=1,
        max_size=5,
        open=True,
    )
    log.info("DB pool initialised (min=1, max=5)")


@contextlib.contextmanager
def get_conn():
    """Yield a pooled connection. Use for short-lived transactions only —
    never hold open during inference or approval (Section C)."""
    assert pool is not None, "Pool not initialised — call init_pool() first"
    with pool.connection() as conn:
        yield conn


def health_ping() -> bool:
    """Touch the DB to prove connectivity — used by the /health endpoint
    and the external 3-minute keepalive (Section C)."""
    try:
        with get_conn() as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        log.exception("Health ping failed")
        return False


def close_pool() -> None:
    """Close the connection pool cleanly on shutdown."""
    global pool
    if pool is not None:
        try:
            pool.close()
        except Exception:
            log.exception("Error closing DB pool")
        finally:
            pool = None
            log.info("DB pool closed")

