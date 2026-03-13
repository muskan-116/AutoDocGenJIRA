# app/routes/auth.py
import os
import httpx
import bcrypt
import jwt
import json
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Request, Response, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse, HTMLResponse
from pydantic import BaseModel, EmailStr
from bson import ObjectId

from app.models.user_model import find_user_by_email, create_user

router = APIRouter()

JWT_SECRET = os.getenv("JWT_SECRET", "devsecret")
JWT_EXPIRES_IN = os.getenv("JWT_EXPIRES_IN", "15m")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
BASE_URL = os.getenv("BASE_URL", "http://localhost:4000")


# -------------------------------
# Models
# -------------------------------
class LoginPayload(BaseModel):
    email: EmailStr
    password: str


class RegisterPayload(BaseModel):
    email: EmailStr
    password: str
    name: Optional[str] = None


# -------------------------------
# Helpers
# -------------------------------
def issue_token(response: Response, user: dict):
    token = jwt.encode(
        {
            "id": str(user["_id"]),
            "email": user["email"],
            "exp": datetime.utcnow() + timedelta(minutes=15)
        },
        JWT_SECRET,
        algorithm="HS256"
    )

    # ✅ Railway pe hamesha production treat karo
    is_prod = os.getenv("NODE_ENV") == "production" or os.getenv("RAILWAY_ENVIRONMENT") is not None

    response.set_cookie(
        key="token",
        value=token,
        httponly=True,
        secure=True,        # ✅ HTTPS pe hamesha True
        samesite="none",    # ✅ cross-origin ke liye zaroori
        path="/",
        max_age=900         # ✅ 15 min
    )

    return token


def serialize_user(user: dict) -> dict:
    user_copy = user.copy()
    if "_id" in user_copy and isinstance(user_copy["_id"], ObjectId):
        user_copy["_id"] = str(user_copy["_id"])
    if "createdAt" in user_copy and isinstance(user_copy["createdAt"], datetime):
        user_copy["createdAt"] = user_copy["createdAt"].isoformat()
    return user_copy


# -------------------------------
# Logout
# -------------------------------
@router.post("/logout")
async def logout(response: Response):
    response = JSONResponse({"message": "Logged out successfully"})
    response.delete_cookie(
        key="token",
        path="/",
        httponly=True,
        samesite="none",
        secure=True
    )
    return response


# -------------------------------
# Signup
# -------------------------------
@router.post("/signup")
@router.post("/register")
async def signup(payload: RegisterPayload, request: Request):
    app = request.app
    existing = await find_user_by_email(app, payload.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    pw_hash = bcrypt.hashpw(payload.password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    user_doc = {
        "email": payload.email,
        "name": payload.name,
        "passwordHash": pw_hash,
        "providers": {},
        "createdAt": datetime.utcnow(),
    }
    new_user = await create_user(app, user_doc)
    new_user.pop("passwordHash", None)
    safe_user = serialize_user(new_user)

    resp = JSONResponse({"message": "User registered successfully", "user": safe_user})
    issue_token(resp, safe_user)
    return resp


# -------------------------------
# Signin
# -------------------------------
@router.post("/signin")
@router.post("/login")
async def signin(payload: LoginPayload, request: Request):
    app = request.app
    user = await find_user_by_email(app, payload.email)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not bcrypt.checkpw(payload.password.encode("utf-8"), user.get("passwordHash", "").encode("utf-8")):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user.pop("passwordHash", None)
    safe_user = serialize_user(user)

    resp = JSONResponse({"message": "Logged in successfully", "user": safe_user})
    issue_token(resp, safe_user)
    return resp


# -------------------------------
# Google OAuth
# -------------------------------
@router.get("/google")
async def google_auth():
    client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    redirect_uri = BASE_URL + "/auth/google/callback"
    scope = "openid email profile"
    url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&scope={scope}"
        f"&access_type=offline&prompt=consent"
    )
    return RedirectResponse(url)


@router.get("/google/callback")
async def google_callback(request: Request):
    code = request.query_params.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": BASE_URL + "/auth/google/callback",
    }

    async with httpx.AsyncClient() as client:
        token_res = await client.post(token_url, data=data)
        token_res.raise_for_status()
        tokens = token_res.json()
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        user_res = await client.get("https://www.googleapis.com/oauth2/v2/userinfo", headers=headers)
        user_res.raise_for_status()
        google_user = user_res.json()

    email = google_user.get("email")
    name = google_user.get("name")
    if not email:
        raise HTTPException(status_code=400, detail="Google account has no email")

    app = request.app
    user = await find_user_by_email(app, email)
    if not user:
        user_doc = {
            "email": email,
            "name": name,
            "passwordHash": None,
            "providers": {"google": True},
            "createdAt": datetime.utcnow(),
        }
        user = await create_user(app, user_doc)

    safe_user = serialize_user(user)
    safe_user_json = json.dumps(safe_user)

    resp = HTMLResponse(
        '<script>'
        f'localStorage.setItem("loggedInUser", {safe_user_json});'
        f'window.location.href = "{FRONTEND_URL}/dashboard";'
        '</script>'
    )
    issue_token(resp, safe_user)
    return resp


# -------------------------------
# GitHub OAuth
# -------------------------------
@router.get("/github")
async def github_auth():
    client_id = os.getenv("GITHUB_CLIENT_ID", "")
    redirect_uri = BASE_URL + "/auth/github/callback"
    url = (
        "https://github.com/login/oauth/authorize"
        f"?client_id={client_id}&redirect_uri={redirect_uri}&scope=user:email"
    )
    return RedirectResponse(url)


@router.get("/github/callback")
async def github_callback(request: Request):
    code = request.query_params.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="Missing GitHub code")

    token_url = "https://github.com/login/oauth/access_token"
    data = {
        "client_id": os.getenv("GITHUB_CLIENT_ID"),
        "client_secret": os.getenv("GITHUB_CLIENT_SECRET"),
        "code": code
    }
    headers = {"Accept": "application/json"}

    async with httpx.AsyncClient() as client:
        token_res = await client.post(token_url, data=data, headers=headers)
        token_res.raise_for_status()
        tokens = token_res.json()
        access_token = tokens.get("access_token")
        if not access_token:
            raise HTTPException(status_code=400, detail="GitHub token missing")

        user_res = await client.get("https://api.github.com/user", headers={"Authorization": f"Bearer {access_token}"})
        user_res.raise_for_status()
        github_user = user_res.json()

        email_res = await client.get("https://api.github.com/user/emails", headers={"Authorization": f"Bearer {access_token}"})
        email_res.raise_for_status()
        emails = email_res.json()

    primary_email = next((e["email"] for e in emails if e.get("primary") and e.get("verified")), None)
    if not primary_email:
        raise HTTPException(status_code=400, detail="No verified GitHub email")

    app = request.app
    user = await find_user_by_email(app, primary_email)
    if not user:
        user_doc = {
            "email": primary_email,
            "name": github_user.get("name") or github_user.get("login"),
            "passwordHash": None,
            "providers": {"github": True},
            "createdAt": datetime.utcnow(),
        }
        user = await create_user(app, user_doc)

    safe_user = serialize_user(user)
    safe_user_json = json.dumps(safe_user)

    resp = HTMLResponse(
        '<script>'
        f'localStorage.setItem("loggedInUser", {safe_user_json});'
        f'window.location.href = "{FRONTEND_URL}/dashboard";'
        '</script>'
    )
    issue_token(resp, safe_user)
    return resp
```

GitHub pe update karo aur Railway mein variable add karo:
```
NODE_ENV = production
