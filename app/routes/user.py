# app/routes/user.py
from fastapi import APIRouter, Request, Depends
from app.middleware.auth_middleware import get_current_user
from app.models.user_model import find_user_by_id
from fastapi.responses import JSONResponse

router = APIRouter()

@router.get("/me")
async def get_me(request: Request, current_user = Depends(get_current_user)):
    # current_user has 'id' from JWT
    user = await find_user_by_id(request.app, current_user.get("id"))
    if not user:
        return JSONResponse(status_code=404, content={"error": "User not found"})
    # remove passwordHash before returning
    user.pop("passwordHash", None)
    # ensure _id is serializable (motor returns ObjectId)
    if "_id" in user:
        user["_id"] = str(user["_id"])
    return user
