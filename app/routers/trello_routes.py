from fastapi import APIRouter, Request, Query
from fastapi.responses import RedirectResponse, JSONResponse
from app.services.trello_service import connect_to_trello, save_token, get_user_boards

trello_router = APIRouter(prefix="/trello", tags=["Trello"])

# ---------- 1️⃣ Connect to Trello ----------
@trello_router.get("/connect")
def connect():
    # Redirect to Trello authorization page
    return connect_to_trello()

# ---------- Trello OAuth Callback ----------
@trello_router.get("/callback")
def trello_callback():
    """
    Trello redirects here after user authorization.
    We simply forward the user to the React frontend,
    where the token will be read from the URL hash.
    """
    return RedirectResponse("http://localhost:5173/boards")  # React route

# ---------- 2️⃣ Save token ----------
@trello_router.post("/save_token")
async def save_user_token_endpoint(request: Request):
    data = await request.json()
    user_id = data.get("user_id")
    token = data.get("token")
    if not user_id or not token:
        return JSONResponse({"status": "error", "message": "user_id and token required"}, status_code=400)
    
    result = save_token(user_id, token)
    return JSONResponse(result)

# ---------- 3️⃣ Fetch user boards ----------
@trello_router.get("/boards")
def fetch_boards(user_id: str = Query(...)):
    result = get_user_boards(user_id)
    return JSONResponse(result)
