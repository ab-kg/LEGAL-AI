"""
Authentication routes
=====================
Registration, sign-in, and identity lookup.

These are the only routes reachable without a token, alongside ``/api/health``.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from src.core.common import config
from src.core.common.security import (
    create_access_token,
    create_user_record,
    get_current_user,
    validate_password,
    validate_username,
    verify_password,
)
from src.api.deps import get_db

router = APIRouter(prefix="/api", tags=["auth"])

class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=72)


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(credentials: Credentials, db=Depends(get_db)):
    """Create an account and return a ready-to-use token."""
    username = validate_username(credentials.username)
    validate_password(credentials.password)

    if db[config.USERS_COLLECTION].find_one({"username": username}):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That username is already taken.",
        )

    create_user_record(db, config.USERS_COLLECTION, username, credentials.password, role="user")
    return {"token": create_access_token(username, "user"), "username": username, "role": "user"}


@router.post("/login")
def login(credentials: Credentials, db=Depends(get_db)):
    """Authenticate and issue a JWT."""
    username = credentials.username.strip().lower()
    user = db[config.USERS_COLLECTION].find_one({"username": username})

    # Identical message for unknown-user and wrong-password so the response
    # cannot be used to enumerate accounts.
    if user is None or not verify_password(credentials.password, user["password"]):
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    role = user.get("role", "user")
    return {"token": create_access_token(username, role), "username": username, "role": role}


@router.get("/me")
def whoami(user: dict = Depends(get_current_user)):
    """Return the authenticated caller's identity."""
    return user
