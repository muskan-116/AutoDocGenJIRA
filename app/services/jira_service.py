import os
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

JIRA_BASE_URL = "https://api.atlassian.com"
JIRA_CLIENT_ID = os.getenv("JIRA_CLIENT_ID")
JIRA_CLIENT_SECRET = os.getenv("JIRA_CLIENT_SECRET")
JIRA_REDIRECT_URI = os.getenv("JIRA_REDIRECT_URI")

# ================= TOKEN STORAGE =================
async def save_jira_token(db, user_id: str, token_data: dict):
    await db["jira_tokens"].update_one(
        {"user_id": user_id},
        {
            "$set": {
                "access_token": token_data.get("access_token"),
                "refresh_token": token_data.get("refresh_token"),
                "expires_in": token_data.get("expires_in"),
                "updated_at": datetime.utcnow()
            }
        },
        upsert=True
    )

# ================= TOKEN EXCHANGE =================
def exchange_code_for_token(code: str):
    url = "https://auth.atlassian.com/oauth/token"

    payload = {
        "grant_type": "authorization_code",
        "client_id": JIRA_CLIENT_ID,
        "client_secret": JIRA_CLIENT_SECRET,
        "code": code,
        "redirect_uri": JIRA_REDIRECT_URI
    }

    res = requests.post(url, json=payload)
    res.raise_for_status()
    return res.json()

# ================= CLOUD ID =================
def get_cloud_id(access_token: str) -> str:
    res = requests.get(
        "https://api.atlassian.com/oauth/token/accessible-resources",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json"
        }
    )
    res.raise_for_status()

    resources = res.json()
    if not resources:
        raise Exception("No Jira sites found")

    return resources[0]["id"]

# ================= ACCESS TOKEN =================
async def get_access_token(db, user_id: str) -> str:
    token = await db["jira_tokens"].find_one({"user_id": user_id})
    if not token:
        raise Exception("Jira not connected")

    return token["access_token"]

# ================= CORE REQUEST =================
async def jira_request(db, user_id: str, method: str, endpoint: str):
    access_token = await get_access_token(db, user_id)
    cloud_id = get_cloud_id(access_token)

    url = f"{JIRA_BASE_URL}/ex/jira/{cloud_id}{endpoint}"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    res = requests.request(method, url, headers=headers)
    res.raise_for_status()
    return res.json()

# ================= PROJECTS =================
async def get_projects(db, user_id: str):
    data = await jira_request(
        db,
        user_id,
        "GET",
        "/rest/api/3/project/search"
    )

    # IMPORTANT: return only projects list
    return data.get("values", [])

# ================= PROJECT ISSUES =================
async def get_project_issues(db, user_id: str, project_key: str):
    jql = f"project={project_key}"
    endpoint = f"/rest/api/3/search?jql={jql}&maxResults=100"
    return await jira_request(db, user_id, "GET", endpoint)

# ================= STRUCTURE FOR DOCS =================
def structure_jira_data(jira_data: dict):
    epics, stories, tasks = [], [], []

    for issue in jira_data.get("issues", []):
        fields = issue["fields"]
        issue_type = fields["issuetype"]["name"]

        item = {
            "key": issue["key"],
            "title": fields["summary"],
            "description": fields.get("description"),
            "status": fields["status"]["name"]
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
        "tasks": tasks
    }
