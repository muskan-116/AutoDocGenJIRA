# app/routers/jira_routes.py

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from urllib.parse import urlencode
from datetime import datetime, timedelta
import uuid
import os

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


# ---------- 1️⃣ AUTHORIZE ----------
@router.get("/authorize")
async def authorize(
    user_id: str,          # ✅ query param se lo — browser redirect pe JWT header nahi jata
    db=Depends(get_db)
):
    state = f"{user_id}_{uuid.uuid4().hex}"

    # ✅ MongoDB mein state store karo
    await db["oauth_states"].insert_one({
        "state": state,
        "user_id": str(user_id),
        "expires_at": datetime.utcnow() + timedelta(minutes=5),
        "created_at": datetime.utcnow()
    })

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
async def callback(
    code: str,
    state: str,
    db=Depends(get_db)
):
    # ✅ MongoDB se state fetch
    state_doc = await db["oauth_states"].find_one({"state": state})

    if not state_doc:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired OAuth state. Please try connecting Jira again."
        )

    # ✅ Expiry check
    if datetime.utcnow() > state_doc["expires_at"]:
        await db["oauth_states"].delete_one({"state": state})
        raise HTTPException(
            status_code=400,
            detail="OAuth state expired. Please try connecting Jira again."
        )

    # ✅ One-time use — foran delete
    await db["oauth_states"].delete_one({"state": state})

    user_id = state_doc["user_id"]

    # ✅ Token exchange (async)
    token_data = await exchange_code_for_token(code)

    if not token_data or not token_data.get("access_token"):
        raise HTTPException(
            status_code=400,
            detail="Failed to get access token from Jira. Please try again."
        )

    await save_jira_token(db, user_id, token_data)

    return RedirectResponse(f"{FRONTEND_URL}/jira-success")


# ---------- 3️⃣ CONNECTION STATUS ----------
@router.get("/status")
async def jira_status(
    user=Depends(get_current_user),
    db=Depends(get_db)
):
    token = await db["jira_tokens"].find_one({"user_id": str(user["id"])})
    return {"connected": bool(token and token.get("access_token"))}


# ---------- 4️⃣ FETCH PROJECTS ----------
@router.get("/projects")
async def fetch_projects(
    user=Depends(get_current_user),
    db=Depends(get_db)
):
    try:
        projects = await get_projects(db, user["id"])
        return {"projects": projects}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------- 5️⃣ DISCONNECT ----------
@router.delete("/disconnect")
async def disconnect_jira(
    user=Depends(get_current_user),
    db=Depends(get_db)
):
    await db["jira_tokens"].delete_one({"user_id": str(user["id"])})
    return {"message": "Jira disconnected successfully"}


# ---------- 6️⃣ GENERATE DOCUMENT ----------
@router.post("/generate-document")
async def generate_document(
    project_key: str,
    template: str,
    user=Depends(get_current_user),
    db=Depends(get_db)
):
    if not template:
        raise HTTPException(status_code=400, detail="Template is required")
    if not project_key:
        raise HTTPException(status_code=400, detail="Project key is required")

    try:
        jira_raw = await get_project_issues(db, user["id"], project_key)
        jira_structured = structure_jira_data(jira_raw)

        if jira_structured["summary"]["total"] == 0:
            raise HTTPException(
                status_code=404,
                detail=f"No issues found in project '{project_key}'. Check project key."
            )

        return await execute_workflow(
            user_id=user["id"],
            project_id=project_key,
            data={"template": template, "jira_data": jira_structured},
            db=db
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
