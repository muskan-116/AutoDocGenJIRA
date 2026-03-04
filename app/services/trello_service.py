import asyncio
import os
import re
import httpx
from fastapi.responses import RedirectResponse
from dotenv import load_dotenv
from app.models.user_token_model import save_user_token, get_user_token

load_dotenv()

TRELLO_API_KEY = os.getenv("TRELLO_API_KEY")
BASE_URL = os.getenv("BASE_URL")

if not TRELLO_API_KEY:
    raise RuntimeError("TRELLO_API_KEY missing from environment")
if not BASE_URL:
    raise RuntimeError("BASE_URL missing from environment")


# --------------------------------------------------
# OAuth: Connect to Trello
# --------------------------------------------------
def connect_to_trello(user_id: str):
    """
    Returns a RedirectResponse to authorize the user with Trello.
    Includes the user_id as a state parameter in the callback.
    """
    return_url = f"{BASE_URL}/trello/callback?user_id={user_id}"
    url = (
        "https://trello.com/1/authorize"
        "?expiration=30days"
        "&name=PMDocGen"
        "&scope=read,write"
        "&response_type=token"
        f"&key={TRELLO_API_KEY}"
        f"&return_url={return_url}"
    )
    return RedirectResponse(url)



# --------------------------------------------------
# Save Trello Token
# --------------------------------------------------
async def save_token(user_id: str, trello_token: str, db):
    """
    Saves the Trello token for a given user in MongoDB.
    """
    if not user_id or not trello_token:
        raise ValueError("user_id and trello_token are required")

    await save_user_token(user_id, trello_token, db)
    return {"status": "success", "message": "Trello token saved"}


# --------------------------------------------------
# Fetch Boards (UI dropdown source)
# --------------------------------------------------
async def fetch_user_boards_from_trello(user_id: str, db):
    """
    Fetch all boards of the user using their Trello token.
    """
    token = await get_user_token(user_id, db)
    if not token:
        raise ValueError("User not connected to Trello")

    url = "https://api.trello.com/1/members/me/boards"
    params = {
        "key": TRELLO_API_KEY,
        "token": token,
        "fields": "id,name,url"
    }

    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.get(url, params=params)

    if res.status_code != 200:
        raise RuntimeError(res.text)

    return [
        {
            "board_id": b["id"],
            "board_name": b["name"],
            "board_url": b["url"]
        }
        for b in res.json()
    ]


# --------------------------------------------------
# Get Boards That Already Have Generated Docs
# --------------------------------------------------
async def get_user_generated_boards(user_id: str, db):
    """
    Return boards for which documents already exist for the user.
    """
    cursor = db["generated_docs"].find(
        {"user_id": user_id},
        {
            "_id": 0,
            "project_id": 1,
            "board_id": 1,
            "board_name": 1,
            "template_name": 1
        }
    )
    boards = [doc async for doc in cursor]
    return boards if boards else []


# --------------------------------------------------
# Helpers
# --------------------------------------------------
def extract_board_id_from_url(url: str) -> str:
    if not url:
        return ""
    match = re.search(r"trello\.com/b/([a-zA-Z0-9]+)", url)
    return match.group(1) if match else ""


# --------------------------------------------------
# Get Board Name
# --------------------------------------------------
async def get_board_name(user_id: str, project_id: str, db=None) -> str:
    """
    Fetch the board name using the user's token.
    """
    if not project_id or project_id == "undefined":
        return "Untitled Project"

    if db is None:
        print("❌ DB instance not provided to get_board_name")
        return "Untitled Project"

    token = await get_user_token(user_id, db)
    if not token:
        print("❌ Trello token missing for user:", user_id)
        return "Untitled Project"

    url = f"https://api.trello.com/1/boards/{project_id}"
    params = {"key": TRELLO_API_KEY, "token": token, "fields": "name"}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.get(url, params=params)

        if res.status_code == 200:
            name = res.json().get("name")
            if name:
                return name

        print(f"❌ Trello board fetch failed [{res.status_code}]: {res.text}")

    except Exception as e:
        print("❌ Exception while fetching board name:", e)

    return "Untitled Project"


# --------------------------------------------------
# Register Webhook
# --------------------------------------------------
async def register_trello_webhook(board_id: str, callback_url: str, token: str, key: str):
    async with httpx.AsyncClient(timeout=15) as client:

        # 1️⃣ Check existing webhooks
        check_res = await client.get(
            f"https://api.trello.com/1/tokens/{token}/webhooks",
            params={"key": key, "token": token}
        )
        check_res.raise_for_status()
        existing_hooks = check_res.json()

        # 2️⃣ Avoid duplicates
        for hook in existing_hooks:
            if hook.get("idModel") == board_id and hook.get("callbackURL") == callback_url:
                print(f"Webhook already exists for board {board_id}")
                return hook  # ✅ Skip creating

        # 3️⃣ Register webhook
        try:
            create_res = await client.post(
                "https://api.trello.com/1/webhooks",
                params={"key": key, "token": token},
                json={
                    "idModel": board_id,
                    "callbackURL": callback_url,
                    "description": "AutoDocGen Webhook"
                }
            )
            create_res.raise_for_status()
            print(f"Webhook registered for board {board_id}")
            return create_res.json()
        except httpx.HTTPStatusError as e:
            print(f"❌ Failed to create webhook: {e.response.status_code}, {e.response.text}")
            return None

