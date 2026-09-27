import datetime
import hashlib
import logging
import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.config import settings
from app.db import get_conn

log = logging.getLogger(__name__)
router = APIRouter(tags=["auth"])

bearer_scheme = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    email: str
    password: str


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return hash_password(plain_password) == hashed_password


def create_access_token(owner_id: str, email: str) -> str:
    payload = {
        "owner_id": str(owner_id),
        "email": email,
        "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=24),
        "iat": datetime.datetime.now(datetime.timezone.utc),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


async def get_current_owner(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> dict:
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "unauthorized", "message": "Missing bearer token"}},
        )
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        owner_id = payload.get("owner_id")
        email = payload.get("email")
        if not owner_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": {"code": "unauthorized", "message": "Invalid token claims"}},
            )
        return {"owner_id": owner_id, "email": email}
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "unauthorized", "message": "Token expired"}},
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "unauthorized", "message": "Invalid token"}},
        )


def check_business_membership(owner_id: str, business_id: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM owner_business_memberships
            WHERE owner_id = %s AND business_id = %s
            """,
            (owner_id, business_id),
        ).fetchone()
        return row is not None


@router.post("/auth/login")
async def login(req: LoginRequest):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT owner_id, email, password_hash FROM owners WHERE email = %s",
            (req.email.lower().strip(),),
        ).fetchone()

    if not row or not verify_password(req.password, row[2]):
        return JSONResponse(
            status_code=401,
            content={"error": {"code": "unauthorized", "message": "Invalid email or password"}},
        )

    token = create_access_token(owner_id=row[0], email=row[1])
    return {"token": token}


@router.post("/auth/register")
async def register(req: LoginRequest):
    with get_conn() as conn:
        # Check if email already exists
        row = conn.execute("SELECT owner_id FROM owners WHERE email = %s", (req.email.lower().strip(),)).fetchone()
        if row:
            return JSONResponse(
                status_code=400,
                content={"error": {"code": "bad_request", "message": "Email already registered"}}
            )
        
        # Insert new owner
        hashed_pw = hash_password(req.password)
        new_owner = conn.execute(
            "INSERT INTO owners (email, password_hash) VALUES (%s, %s) RETURNING owner_id",
            (req.email.lower().strip(), hashed_pw)
        ).fetchone()
        
        owner_id = new_owner[0]
        
        # Assign them to a test business (e.g. test_shop) so they aren't empty
        conn.execute(
            "INSERT INTO owner_business_memberships (owner_id, business_id) VALUES (%s, 'test_shop') ON CONFLICT DO NOTHING",
            (owner_id,)
        )
        
        conn.commit()

    token = create_access_token(owner_id=owner_id, email=req.email.lower().strip())
    return {"token": token}



@router.get("/auth/me")
async def get_me(owner: dict = Depends(get_current_owner)):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT business_id FROM owner_business_memberships WHERE owner_id = %s",
            (owner["owner_id"],),
        ).fetchall()

    businesses = [r[0] for r in rows]
    return {
        "owner_id": str(owner["owner_id"]),
        "email": owner["email"],
        "businesses": businesses,
    }


@router.get("/businesses")
async def get_businesses(owner: dict = Depends(get_current_owner)):
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT b.business_id, b.name, b.business_type
            FROM businesses b
            JOIN owner_business_memberships m ON b.business_id = m.business_id
            WHERE m.owner_id = %s
            ORDER BY b.business_id
            """,
            (owner["owner_id"],),
        ).fetchall()

    # Per INTEGRATION_CHECKLIST: Owner without membership gets 403, not an empty list
    if not rows:
        return JSONResponse(
            status_code=403,
            content={"error": {"code": "forbidden", "message": "No business memberships found for this owner"}},
        )

    return [{"business_id": r[0], "name": r[1], "business_type": r[2]} for r in rows]


# Preserved stubs for other teammates (Jagdeep / Sam / etc.)
@router.get("/businesses/{id}/catalog")
async def get_catalog(id: str):
    raise HTTPException(status_code=501, detail="Not implemented: Get catalog route pending implementation.")


@router.get("/businesses/{id}/services")
async def get_services(id: str):
    raise HTTPException(status_code=501, detail="Not implemented: Get services route pending implementation.")


@router.get("/businesses/{id}/slots")
async def get_slots(id: str, service_id: str = None):
    raise HTTPException(status_code=501, detail="Not implemented: Get slots route pending implementation.")


@router.get("/businesses/{id}/orders")
async def get_orders(id: str, status: str = None):
    raise HTTPException(status_code=501, detail="Not implemented: Get orders route pending implementation.")


@router.get("/businesses/{id}/holds")
async def get_holds(id: str):
    raise HTTPException(status_code=501, detail="Not implemented: Get holds route pending implementation by Jagdeep.")


@router.post("/businesses/{id}/holds")
async def resolve_hold(id: str, payload: dict):
    raise HTTPException(status_code=501, detail="Not implemented: Resolve hold route pending implementation by Jagdeep.")


@router.get("/businesses/{id}/evidence")
async def get_evidence(id: str):
    raise HTTPException(status_code=501, detail="Not implemented: Get evidence route pending implementation by Jagdeep.")
