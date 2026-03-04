from fastapi import APIRouter, Request, Response, BackgroundTasks
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
from app.services.workflow_service import execute_workflow

router = APIRouter()



async def process_trello_action(payload: dict, db):
    notifications_collection = db["notifications"]
    boards_collection = db["tokens"]  # Your user-board-token mapping

    action = payload.get("action")
    if not action:
        return

    event_type = action.get("type", "unknown")
    data = action.get("data", {})
    board = data.get("board", {})
    card = data.get("card", {})
    member = action.get("memberCreator", {})

    # Find user for this board
    board_doc = await boards_collection.find_one({"board_id": board.get("id")})
    if not board_doc:
        # Board not registered → ignore event
        return

    user_id = board_doc.get("user_id")  # now dynamic per board

    print(f"🔔 Board change detected for user {user_id}: {event_type} on {board.get('name')} / {card.get('name')}")

    # Save notification
    notification_doc = {
        "user_id": user_id,
        "board_id": board.get("id"),
        "board_name": board.get("name"),
        "event_type": event_type,
        "card_name": card.get("name"),
        "changes": {"user": member.get("fullName")},
        "timestamp": datetime.utcnow()
    }
    await notifications_collection.insert_one(notification_doc)
# HEAD request for Trello verification
@router.head("/pm")
async def trello_webhook_verify():
    return Response(status_code=200)


# POST request for Trello events
@router.post("/pm")
async def trello_webhook(
    request: Request,
    background_tasks: BackgroundTasks
):
    try:
        payload = await request.json()
    except Exception:
        return Response(status_code=200)

    background_tasks.add_task(
        process_trello_action,
        payload,
        request.app.state.db
    )

    return Response(status_code=200)



# Endpoint to fetch notifications for frontend
@router.get("/notifications/{user_id}")
async def get_notifications(user_id: str):
    notifications = await notifications_collection.find({"user_id": user_id}).sort("timestamp", -1).to_list(100)
    return notifications
