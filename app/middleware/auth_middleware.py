# app/middleware/auth_middleware.py
from fastapi import Request, HTTPException, Depends
import jwt
import os
from typing import Optional

JWT_SECRET = os.getenv("JWT_SECRET", "devsecret")

async def get_current_user(request: Request) -> Optional[dict]:
    # try cookie first (same as your Express cookie behavior)
    token = request.cookies.get("token")
    if not token:
        # also allow Authorization header if frontend uses it
        auth = request.headers.get("Authorization")
        if auth and auth.startswith("Bearer "):
            token = auth.split(" ", 1)[1]

    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        # payload expected { id, email }
        return {"id": payload.get("id"), "email": payload.get("email")}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
