# app/routers/jira_routes.py

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
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
from app.middleware.db import get_db
from app.middleware.auth_middleware import get_current_user

router = APIRouter(tags=["Jira"])

JIRA_CLIENT_ID = os.getenv("JIRA_CLIENT_ID")
JIRA_REDIRECT_URI = os.getenv("JIRA_REDIRECT_URI")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

oauth_state_store = {}

# ---------- 1️⃣ AUTHORIZE ----------
@router.get("/authorize")
def authorize(user=Depends(get_current_user)):
    state = f"{user['id']}_{uuid.uuid4().hex}"
    oauth_state_store[state] = user["id"]

    jira_auth_url = (
        "https://auth.atlassian.com/authorize?"
        "audience=api.atlassian.com"
        f"&client_id={JIRA_CLIENT_ID}"
        "&scope=read:jira-user read:jira-work write:jira-work offline_access"
        f"&redirect_uri={JIRA_REDIRECT_URI}"
        f"&state={state}"
        "&response_type=code"
        "&prompt=consent"
    )

    return RedirectResponse(jira_auth_url)

# ---------- 2️⃣ CALLBACK ----------
@router.get("/callback")
async def callback(code: str, state: str, db=Depends(get_db)):
    user_id = oauth_state_store.pop(state, None)

    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    token_data = exchange_code_for_token(code)
    await save_jira_token(db, user_id, token_data)

    return RedirectResponse(f"{FRONTEND_URL}/jira-success")

# ---------- 3️⃣ FETCH PROJECTS ----------
@router.get("/projects")
async def fetch_projects(db=Depends(get_db), user=Depends(get_current_user)):
    projects = await get_projects(db, user["id"])
    return {"projects": projects}

# ---------- 4️⃣ GENERATE DOCUMENT ----------
@router.post("/generate-document")
async def generate_document(
    project_key: str,
    template: str,
    db=Depends(get_db),
    user=Depends(get_current_user)
):
    if not template:
        raise HTTPException(status_code=400, detail="Template is required")

    # Fetch Jira issues
    jira_raw = await get_project_issues(db, user["id"], project_key)

    # Structure Jira data (Epics / Stories / Tasks)
    jira_structured = structure_jira_data(jira_raw)

    # Pass Jira data into workflow (Trello remains untouched)
    return await execute_workflow(
        user_id=user["id"],
        project_id=project_key,
        data={
            "template": template,
            "jira_data": jira_structured
        },
        db=db
    )
