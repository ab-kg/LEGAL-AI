"""
Authentication & Authorization
===============================
Password hashing, JWT issuing/verification, and the FastAPI dependencies that
gate every non-public endpoint.

Before this module the API had a login route that issued a JWT but nothing ever
verified it, so every endpoint was reachable by anyone who knew the URL. The
`get_current_user` dependency below is the single enforcement point; endpoints
opt in by declaring `user: dict = Depends(get_current_user)`.
"""

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# ─── Token configuration ────────────────────────────────────────────

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRES = timedelta(hours=int(os.getenv("ACCESS_TOKEN_HOURS", "24")))

# bcrypt silently truncates at 72 bytes, so reject rather than accept a
# password whose tail is ignored.
MAX_PASSWORD_BYTES = 72
MIN_PASSWORD_LENGTH = 8

_ephemeral = False
JWT_SECRET = os.getenv("JWT_SECRET", "").strip()
if not JWT_SECRET:
    # Keep local development usable without silently shipping a public constant
    # as the signing key. Tokens simply stop surviving a restart.
    JWT_SECRET = os.urandom(32).hex()
    _ephemeral = True
    print(
        "=" * 70 + "\n"
        "⚠️  JWT_SECRET is not set. Generated an ephemeral signing key.\n"
        "    Tokens will be invalidated on every restart.\n"
        "    Set JWT_SECRET in your environment before deploying.\n"
        + "=" * 70
    )

bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")

# ─── Password hashing ───────────────────────────────────────────────

def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(password: str, hashed: str) -> bool:
    """Constant-time comparison of a plaintext password against a stored hash."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False

def validate_password(password: str) -> None:
    """Raise HTTP 422 if the password cannot be stored or is too weak."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Password must be at least {MIN_PASSWORD_LENGTH} characters.",
        )
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Password must be at most {MAX_PASSWORD_BYTES} bytes.",
        )


def normalize_username(username: str) -> str:
    """Usernames are matched case-insensitively and stored lowercased."""
    return username.strip().lower()

def validate_username(username: str) -> str:
    """Return a validated, normalized username or raise HTTP 422."""
    cleaned = normalize_username(username)
    if len(cleaned) < 3 or len(cleaned) > 32:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Username must be between 3 and 32 characters.",
        )
    if not all(c.isalnum() or c in "._-" for c in cleaned):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Username may only contain letters, numbers, and . _ -",
        )
    return cleaned


# ─── Token issuing ──────────────────────────────────────────────────

def create_access_token(username: str, role: str = "user") -> str:
    """Issue a signed JWT carrying the username, role, and an expiry."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "role": role,
        "iat": now,
        "exp": now + ACCESS_TOKEN_EXPIRES,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Verify a JWT's signature and expiry, returning its claims."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ─── Dependencies ───────────────────────────────────────────────────

def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    """Resolve the caller's identity from the Authorization header.

    This is the only place a request is authenticated. Every endpoint that does
    not declare it as a dependency is public by design (`/api/health`,
    `/api/login`, `/api/register`).
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None or not credentials.credentials:
        raise unauthorized

    claims = decode_token(credentials.credentials)
    username = claims.get("sub")
    if not username:
        raise unauthorized

    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not ready.",
        )

    from src.core.common import config

    user = db[config.USERS_COLLECTION].find_one({"username": username})
    if user is None:
        # Token is well-formed but the account is gone (deleted or renamed).
        raise unauthorized
    
    return {
        "id": str(user.get("_id")),
        "username": user["username"],
        "role": user.get("role", "user"),
    }


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """Dependency for endpoints restricted to the admin role."""
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator privileges required.",
        )
    return user

def create_user_record(
    db,
    users_collection: str,
    username: str,
    password: str,
    role: str = "user",
) -> str:
    """Insert a new user document. Raises HTTP 409 if the username is taken."""
    now = datetime.now(timezone.utc)
    result = db[users_collection].insert_one(
        {
            "_id": str(uuid.uuid4()),
            "username": username,
            "password": hash_password(password),
            "role": role,
            "created_at": now,
        }
    )
    return str(result.inserted_id)
