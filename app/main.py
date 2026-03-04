import os
import re
import asyncio
import motor.motor_asyncio
import uvicorn
import httpx
from fastapi import HTTPException
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from dotenv import load_dotenv

# ------------------ Load ENV ------------------
load_dotenv()

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
MONGODB_URI = os.getenv("MONGODB_URI")
DB_NAME = os.getenv("DB_NAME", "Doc_Gen")
PORT = int(os.getenv("PORT", 8080))
BASE_URL = os.getenv("BASE_URL")
TRELLO_API_KEY = os.getenv("TRELLO_API_KEY")
TRELLO_CALLBACK_URL = os.getenv("TRELLO_CALLBACK_URL") or f"{BASE_URL}/pm"

if not MONGODB_URI:
    raise RuntimeError("MONGODB_URI not set")

# ------------------ App ------------------
app = FastAPI()

# ------------------ CORS ------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "https://autodocgen-production.up.railway.app",
        "https://autodocgen3-production-d3e5.up.railway.app",
        "https://autodocgen3-production-952a.up.railway.app",
        "https://autodocgen3-production-2468.up.railway.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------ Routers ------------------
from app.routes import auth as auth_router
from app.routes import user as user_router
from app.routes import templates as templates_router
from app.routes import generated_docs as generated_docs_router
from app.routes.trello_webhook import router as trello_webhook_router

app.include_router(auth_router.router, prefix="/auth")
app.include_router(user_router.router, prefix="/api")
app.include_router(templates_router.router, prefix="/templates")
app.include_router(generated_docs_router.router, prefix="/generated-docs")
app.include_router(trello_webhook_router)  # ✅ ONLY webhook registration

# ------------------ Services ------------------
from app.services.trello_service import (
    connect_to_trello,
    register_trello_webhook
)
from app.models.user_token_model import (
    get_all_user_tokens,
    get_user_token,
    save_user_token
)
from app.services.workflow_service import execute_workflow

# ------------------ MongoDB Startup ------------------
# ------------------ MongoDB Startup ------------------
@app.on_event("startup")
async def startup():
    # ------------------ Connect to MongoDB ------------------
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGODB_URI)
    app.state.mongo_client = client
    app.state.db = client[DB_NAME]
    db = app.state.db

    print("✅ MongoDB connected")

    # ✅ IMPORTANT: Prevent duplicate notifications
    await db["notifications"].create_index(
        "action_id",
        unique=True,
        sparse=True
    )
    print("✅ Notification index ensured")

    # ------------------ Fetch all users with Trello tokens ------------------
    users = await get_all_user_tokens(db)
    if not users:
        print("⚠️ No users with Trello tokens found")
        return

    # ------------------ Prevent multiple startup runs ------------------
    if getattr(app.state, "webhooks_registered", False):
        return
    app.state.webhooks_registered = True

    async with httpx.AsyncClient(timeout=20) as client_http:

        for user in users:
            token = user.get("trello_token")
            user_id = user.get("user_id")

            if not token:
                continue

            # ------------------ Fetch all boards for this user ------------------
            try:
                res = await client_http.get(
                    "https://api.trello.com/1/members/me/boards",
                    params={
                        "key": TRELLO_API_KEY,
                        "token": token,
                        "fields": "id,name"
                    }
                )
                res.raise_for_status()
                boards = res.json()
            except Exception as e:
                print(f"❌ Failed to fetch boards for user {user_id}: {e}")
                continue

            for board in boards:
                board_id = board["id"]
                board_name = board["name"]

                # ------------------ Map board to user in DB ------------------
                await db["board_user_map"].update_one(
                    {"board_id": board_id},
                    {"$set": {"user_id": user_id, "board_name": board_name}},
                    upsert=True
                )

                # ------------------ Safe webhook registration ------------------
                try:
                    check_res = await client_http.get(
                        f"https://api.trello.com/1/tokens/{token}/webhooks",
                        params={"key": TRELLO_API_KEY, "token": token}
                    )
                    check_res.raise_for_status()
                    existing_hooks = check_res.json()

                    if any(
                        hook.get("idModel") == board_id and hook.get("callbackURL") == TRELLO_CALLBACK_URL
                        for hook in existing_hooks
                    ):
                        print(f"⚡ Webhook already exists for board {board_id}")
                        continue

                    create_res = await client_http.post(
                        "https://api.trello.com/1/webhooks",
                        params={"key": TRELLO_API_KEY, "token": token},
                        json={
                            "idModel": board_id,
                            "callbackURL": TRELLO_CALLBACK_URL,
                            "description": "AutoDocGen Webhook"
                        }
                    )
                    create_res.raise_for_status()
                    print(f"✅ Webhook registered for board {board_id}")

                except httpx.HTTPStatusError as e:
                    print(
                        f"❌ Failed to create webhook for board {board_id}: "
                        f"{e.response.status_code}, {e.response.text}"
                    )
                except Exception as e:
                    print(
                        f"❌ Unexpected error registering webhook for board {board_id}: {e}"
                    )

# ------------------ Shutdown ------------------
@app.on_event("shutdown")
async def shutdown():
    app.state.mongo_client.close()

# ------------------ Trello Connect ------------------
@app.get("/trello/connect")
def trello_connect(request: Request):
    user_id = request.query_params.get("user_id")
    return connect_to_trello(user_id)

@app.get("/trello/callback")
def trello_callback():
    return RedirectResponse(f"{FRONTEND_URL}/boards")

# ------------------ Save Trello Token ------------------
@app.post("/trello/save_token")
async def trello_save_token(request: Request):
    data = await request.json()
    user_id = data["user_id"]
    trello_token = data["trello_token"]
    db = app.state.db

    await save_user_token(user_id, trello_token, db)

    async with httpx.AsyncClient(timeout=20) as client:
        res = await client.get(
            "https://api.trello.com/1/members/me/boards",
            params={
                "key": TRELLO_API_KEY,
                "token": trello_token,
                "fields": "id,name,desc",
                "filter": "open"
            }
        )
        boards = res.json()

    for board in boards:
        await db["board_user_map"].update_one(
            {"board_id": board["id"]},
            {"$set": {
                "user_id": user_id,
                "board_name": board["name"],
                "board_desc": board.get("desc", "")
            }},
            upsert=True
        )

    return {"status": "success"}

# ------------------ Boards with Headings ------------------
@app.get("/trello/boards_with_headings")
async def boards_with_headings(user_id: str):
    db = app.state.db
    token = await get_user_token(user_id, db)
    if not token:
        return {"status": "error", "boards": []}

    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.get(
            "https://api.trello.com/1/members/me/boards",
            params={"key": TRELLO_API_KEY, "token": token, "fields": "id,name,desc"}
        )
        boards = res.json()

    docs = await db["generated_docs"].find({"user_id": user_id}).to_list(None)
    doc_map = {d["project_id"]: d for d in docs}

    result = []
    for b in boards:
        raw = doc_map.get(b["id"], {}).get("generated_docs", "")
        headings = re.findall(r"##\s*(.+)", raw)
        result.append({
            "id": b["id"],
            "name": b["name"],
            "desc": b.get("desc", ""),
            "has_generated_doc": b["id"] in doc_map,
            "previous_headings": headings
        })

    return {"status": "success", "boards": result}

# ------------------ Workflow ------------------
@app.post("/workflow/run")
async def run_workflow(request: Request):
    data = await request.json()

    if not all(k in data for k in ("user_id", "project_id", "template")):
        raise HTTPException(status_code=400, detail="Missing required fields")

    return await execute_workflow(
        data["user_id"],
        data["project_id"],
        data,
        db=request.app.state.db
    )


@app.get("/workflow/generated")
async def get_generated_doc(user_id: str, project_id: str, template_name: str):
    db = app.state.db
    collection = db["generated_docs"]
    doc = await collection.find_one({
        "user_id": user_id,
        "project_id": project_id,
        "template_name": template_name
    })
    if not doc:
        return await execute_workflow(user_id, project_id, {"template": template_name}, db=db)

    board_name = doc.get("board_name") or "Unknown Board"
    diagrams = doc.get("generated_diagrams", {})
    for heading, diagram in diagrams.items():
        if "image" in diagram:
            diagram["image"] = f"data:image/png;base64,{diagram['image']}"

    return {
        "status": "success",
        "template_name": template_name,
        "generated_docs": doc.get("generated_docs", ""),
        "generated_diagrams": diagrams,
        "board_name": board_name
    }


# ------------------ Run ------------------
if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=PORT, reload=True)
