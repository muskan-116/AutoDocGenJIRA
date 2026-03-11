import os
import httpx
from datetime import datetime, timedelta
from urllib.parse import quote
from dotenv import load_dotenv

load_dotenv()

JIRA_BASE_URL = "https://api.atlassian.com"
JIRA_CLIENT_ID = os.getenv("JIRA_CLIENT_ID")
JIRA_CLIENT_SECRET = os.getenv("JIRA_CLIENT_SECRET")
JIRA_REDIRECT_URI = os.getenv("JIRA_REDIRECT_URI")

# ================= TOKEN STORAGE =================
async def save_jira_token(db, user_id: str, token_data: dict):
    expires_in = token_data.get("expires_in", 3600)
    expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

    await db["jira_tokens"].update_one(
        {"user_id": str(user_id)},       # ✅ always string — no int/str mismatch
        {
            "$set": {
                "access_token": token_data.get("access_token"),
                "refresh_token": token_data.get("refresh_token"),
                "expires_in": expires_in,
                "expires_at": expires_at,  # ✅ expiry track karo
                "cloud_id": None,           # ✅ reset on new token
                "updated_at": datetime.utcnow()
            }
        },
        upsert=True
    )

# ================= TOKEN EXCHANGE =================
async def exchange_code_for_token(code: str) -> dict:  # ✅ async
    url = "https://auth.atlassian.com/oauth/token"

    payload = {
        "grant_type": "authorization_code",
        "client_id": JIRA_CLIENT_ID,
        "client_secret": JIRA_CLIENT_SECRET,
        "code": code,
        "redirect_uri": JIRA_REDIRECT_URI
    }

    async with httpx.AsyncClient() as client:           # ✅ async httpx
        res = await client.post(url, json=payload)

    if res.status_code != 200:
        raise Exception(f"Token exchange failed: {res.status_code} — {res.text}")

    return res.json()

# ================= TOKEN REFRESH =================
async def refresh_access_token(db, user_id: str) -> str:
    token = await db["jira_tokens"].find_one({"user_id": str(user_id)})

    if not token or not token.get("refresh_token"):
        raise Exception("Jira not connected. Please re-authenticate.")

    payload = {
        "grant_type": "refresh_token",
        "client_id": JIRA_CLIENT_ID,
        "client_secret": JIRA_CLIENT_SECRET,
        "refresh_token": token["refresh_token"]
    }

    async with httpx.AsyncClient() as client:
        res = await client.post(
            "https://auth.atlassian.com/oauth/token",
            json=payload
        )

    if res.status_code != 200:
        raise Exception(f"Token refresh failed: {res.status_code} — {res.text}")

    new_token_data = res.json()
    await save_jira_token(db, user_id, new_token_data)
    return new_token_data["access_token"]

# ================= ACCESS TOKEN =================
async def get_access_token(db, user_id: str) -> str:
    token = await db["jira_tokens"].find_one({"user_id": str(user_id)})

    if not token:
        raise Exception("Jira not connected. Please authenticate first.")

    # ✅ Auto refresh 5 min pehle
    expires_at = token.get("expires_at")
    if expires_at and datetime.utcnow() >= (expires_at - timedelta(minutes=5)):
        return await refresh_access_token(db, user_id)

    return token["access_token"]

# ================= CLOUD ID =================
async def get_cloud_id(db, user_id: str, access_token: str) -> str:  # ✅ async + cached
    # ✅ DB mein cached check karo
    token_doc = await db["jira_tokens"].find_one({"user_id": str(user_id)})
    if token_doc and token_doc.get("cloud_id"):
        return token_doc["cloud_id"]

    async with httpx.AsyncClient() as client:
        res = await client.get(
            "https://api.atlassian.com/oauth/token/accessible-resources",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json"
            }
        )

    if res.status_code != 200:
        raise Exception(f"Failed to fetch Jira sites: {res.status_code} — {res.text}")

    resources = res.json()
    if not resources:
        raise Exception("No Jira sites found. Please create a Jira site at atlassian.com")

    cloud_id = resources[0]["id"]

    # ✅ Cache karo DB mein
    await db["jira_tokens"].update_one(
        {"user_id": str(user_id)},
        {"$set": {"cloud_id": cloud_id}}
    )

    return cloud_id

# ================= CORE REQUEST =================
async def jira_request(db, user_id: str, method: str, endpoint: str) -> dict:
    access_token = await get_access_token(db, user_id)
    cloud_id = await get_cloud_id(db, user_id, access_token)  # ✅ await

    url = f"{JIRA_BASE_URL}/ex/jira/{cloud_id}{endpoint}"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(timeout=30.0) as client:     # ✅ async
        res = await client.request(method, url, headers=headers)

    # ✅ Token expire ho gaya — ek baar retry
    if res.status_code == 401:
        access_token = await refresh_access_token(db, user_id)
        headers["Authorization"] = f"Bearer {access_token}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.request(method, url, headers=headers)

    if res.status_code == 403:
        raise Exception("Jira permission denied. Check OAuth scopes in Atlassian Developer Console.")

    if res.status_code == 404:
        raise Exception(f"Jira resource not found: {endpoint}")

    if not res.is_success:
        raise Exception(f"Jira API error {res.status_code}: {res.text}")

    return res.json()

# ================= PROJECTS =================
async def get_projects(db, user_id: str) -> list:
    data = await jira_request(db, user_id, "GET", "/rest/api/3/project/search")
    return data.get("values", [])

# ================= PROJECT ISSUES =================
async def get_project_issues(db, user_id: str, project_key: str) -> dict:
    jql = quote(f"project={project_key} ORDER BY created DESC")  # ✅ URL encoded
    endpoint = f"/rest/api/3/search?jql={jql}&maxResults=100&fields=summary,description,status,issuetype,assignee,priority"
    return await jira_request(db, user_id, "GET", endpoint)

# ================= STRUCTURE FOR DOCS =================
def structure_jira_data(jira_data: dict) -> dict:
    epics, stories, tasks = [], [], []

    for issue in jira_data.get("issues", []):
        fields = issue.get("fields", {})
        issue_type = fields.get("issuetype", {}).get("name", "Task")

        item = {
            "key": issue.get("key", ""),
            "title": fields.get("summary", "No Title"),
            "description": _extract_description(fields.get("description")),  # ✅ ADF parse
            "status": fields.get("status", {}).get("name", "Unknown"),
            "assignee": fields.get("assignee", {}).get("displayName", "Unassigned") if fields.get("assignee") else "Unassigned",
            "priority": fields.get("priority", {}).get("name", "Medium") if fields.get("priority") else "Medium"
        }

        if issue_type == "Epic":
            epics.append(item)
        elif issue_type in ["Story", "User Story"]:
            stories.append(item)
        else:
            tasks.append(item)

    return {
        "epics": epics,
        "stories": stories,
        "tasks": tasks,
        "summary": {
            "total": len(epics) + len(stories) + len(tasks),
            "epics_count": len(epics),
            "stories_count": len(stories),
            "tasks_count": len(tasks)
        }
    }

# ================= ADF DESCRIPTION PARSER =================
def _extract_description(description) -> str:
    """Jira API v3 returns description in ADF format — extract plain text"""
    if not description:
        return ""
    if isinstance(description, str):
        return description
    if isinstance(description, dict):
        texts = []
        _extract_adf_text(description, texts)
        return " ".join(texts).strip()
    return ""

def _extract_adf_text(node: dict, texts: list):
    """Recursively extract text from Atlassian Document Format"""
    if node.get("type") == "text":
        texts.append(node.get("text", ""))
    for child in node.get("content", []):
        _extract_adf_text(child, texts)
