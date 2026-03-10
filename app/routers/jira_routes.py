from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from urllib.parse import urlencode
import uuid
import os
import redis.asyncio as aioredis

from app.services.jira_service import (
    exchange_code_for_token,
    save_jira_token,
    get_project_issues,
    structure_jira_data,
    get_projects
)
from app.services.workflow_service import execute_workflow
from app.db import get_db
from app.middleware.auth_middleware import get_current_user

router = APIRouter(tags=["Jira"])

JIRA_CLIENT_ID = os.getenv("JIRA_CLIENT_ID")
JIRA_REDIRECT_URI = os.getenv("JIRA_REDIRECT_URI")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# ✅ Async Redis client — Railway multi-instance safe
redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)

# ---------- 1️⃣ AUTHORIZE ----------
@router.get("/authorize")
async def authorize(user=Depends(get_current_user)):
    state = f"{user['id']}_{uuid.uuid4().hex}"

    # ✅ Store in Redis with 5 min expiry — survives multi-instance deploys
    await redis_client.setex(f"oauth_state:{state}", 300, str(user["id"]))

    # ✅ Properly URL-encoded params — no scope/space issues
    params = {
        "audience": "api.atlassian.com",
        "client_id": JIRA_CLIENT_ID,
        "scope": "read:jira-user read:jira-work write:jira-work offline_access",
        "redirect_uri": JIRA_REDIRECT_URI,
        "state": state,
        "response_type": "code",
        "prompt": "consent"
    }

    jira_auth_url = "https://auth.atlassian.com/authorize?" + urlencode(params)
    return RedirectResponse(jira_auth_url)

# ---------- 2️⃣ CALLBACK ----------
@router.get("/callback")
async def callback(code: str, state: str, db=Depends(get_db)):
    # ✅ Fetch and delete state atomically from Redis
    user_id = await redis_client.getdel(f"oauth_state:{state}")

    if not user_id:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired OAuth state. Please try connecting Jira again."
        )

    # ✅ Exchange code for token (now async)
    token_data = await exchange_code_for_token(code)

    if not token_data or not token_data.get("access_token"):
        raise HTTPException(
            status_code=400,
            detail="Failed to get access token from Jira. Please try again."
        )

    await save_jira_token(db, user_id, token_data)

    # ✅ Redirect to frontend success page
    return RedirectResponse(f"{FRONTEND_URL}/jira-success")

# ---------- 3️⃣ FETCH PROJECTS ----------
@router.get("/projects")
async def fetch_projects(db=Depends(get_db), user=Depends(get_current_user)):
    try:
        projects = await get_projects(db, user["id"])
        return {"projects": projects}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ---------- 4️⃣ CHECK CONNECTION STATUS ----------
@router.get("/status")
async def jira_status(db=Depends(get_db), user=Depends(get_current_user)):
    """Check if Jira is connected for current user"""
    token = await db["jira_tokens"].find_one({"user_id": str(user["id"])})
    return {"connected": bool(token and token.get("access_token"))}

# ---------- 5️⃣ DISCONNECT JIRA ----------
@router.delete("/disconnect")
async def disconnect_jira(db=Depends(get_db), user=Depends(get_current_user)):
    """Remove Jira tokens — user will need to re-authenticate"""
    await db["jira_tokens"].delete_one({"user_id": str(user["id"])})
    return {"message": "Jira disconnected successfully"}

# ---------- 6️⃣ GENERATE DOCUMENT ----------
@router.post("/generate-document")
async def generate_document(
    project_key: str,
    template: str,
    db=Depends(get_db),
    user=Depends(get_current_user)
):
    if not template:
        raise HTTPException(status_code=400, detail="Template is required")

    if not project_key:
        raise HTTPException(status_code=400, detail="Project key is required")

    try:
        # Fetch Jira issues
        jira_raw = await get_project_issues(db, user["id"], project_key)

        # Structure Jira data (Epics / Stories / Tasks)
        jira_structured = structure_jira_data(jira_raw)

        if jira_structured["summary"]["total"] == 0:
            raise HTTPException(
                status_code=404,
                detail=f"No issues found in project '{project_key}'. Check project key."
            )

        return await execute_workflow(
            user_id=user["id"],
            project_id=project_key,
            data={
                "template": template,
                "jira_data": jira_structured
            },
            db=db
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
