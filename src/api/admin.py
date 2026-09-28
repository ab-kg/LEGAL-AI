"""
Administrative routes
======================
Reserved for the ``admin`` role. Kept in its own module so the privilege
boundary is visible in the file tree rather than buried in a handler.
"""

from fastapi import APIRouter, Depends

from src.core.common import config
from src.core.common.security import require_admin
from src.api.deps import get_db

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users")
def list_users(db=Depends(get_db), _: dict = Depends(require_admin)):
    """Every account on the system. Password hashes are excluded by projection."""
    return {
        "users": [
            {
                "username": u["username"],
                "role": u.get("role", "user"),
                "created_at": u["created_at"].isoformat() if u.get("created_at") else None,
            }
            for u in db[config.USERS_COLLECTION].find({}, {"password": 0})
        ]
    }
