from fastapi import APIRouter, Request, Response, BackgroundTasks, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from datetime import datetime
from bson import ObjectId
from pymongo.errors import DuplicateKeyError   # ✅ IMPORTANT

from app.db import get_db
from app.services.workflow_service import execute_workflow

router = APIRouter(tags=["Trello Webhook"])


# ----------------------------
# Trello verification
# ----------------------------
@router.head("/pm")
@router.get("/pm")
async def trello_verify():
    return Response(status_code=200)


# ----------------------------
# Webhook receiver
# ----------------------------
@router.post("/pm")
async def trello_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    payload = await request.json()
    background_tasks.add_task(process_event, payload, db=db)
    return Response(status_code=200)


# ----------------------------
# Background processor
# ----------------------------
async def process_event(event: dict, db: AsyncIOMotorDatabase):

    action = event.get("action", {})
    action_id = action.get("id")
    action_type = action.get("type")
    data = action.get("data", {})

    # Only card-related actions
    if not action_type or not action_type.endswith("Card"):
        print("Skipping non-card event:", action_type)
        return

    board_info = data.get("board", {})
    board_id = board_info.get("id")
    board_name = board_info.get("name", "Unknown Board")

    if not board_id:
        return

    board_entry = await db["board_user_map"].find_one({"board_id": board_id})
    if not board_entry:
        return

    user_id = str(board_entry["user_id"])

    card = data.get("card", {})
    card_name = card.get("name") or f"Card {card.get('idShort', '')}"
    card_id = card.get("id", "")

    # ----------------------------
    # Build message
    # ----------------------------
    if action_type == "createCard":
        list_name = data.get("list", {}).get("name", "Unknown List")
        message = f"Card '{card_name}' created in '{list_name}'"

    elif action_type == "updateCard":
        if "listAfter" in data:
            list_name = data.get("listAfter", {}).get("name", "Unknown List")
            message = f"Card '{card_name}' moved to '{list_name}'"
        else:
            message = f"Card '{card_name}' updated"

    elif action_type == "deleteCard":
        message = f"Card '{card_name}' deleted"

    elif action_type == "commentCard":
        comment_text = data.get("text", "")
        message = f"New comment on '{card_name}': {comment_text}"

    elif action_type == "addAttachmentToCard":
        attachment_name = data.get("attachment", {}).get("name", "Attachment")
        message = f"Attachment '{attachment_name}' added to '{card_name}'"

    elif action_type == "removeAttachmentFromCard":
        attachment_name = data.get("attachment", {}).get("name", "Attachment")
        message = f"Attachment '{attachment_name}' removed from '{card_name}'"

    else:
        message = f"Card '{card_name}' action: {action_type}"

    # ----------------------------
    # Notification Document
    # ----------------------------
    notification_doc = {
        "user_id": user_id,
        "board_id": board_id,
        "board_name": board_name,
        "card_id": card_id,
        "action_type": action_type,
        "message": message,
        "is_read": False,
        "created_at": datetime.utcnow(),
        "raw_event": action,
        "action_id": action_id
    }

    # ----------------------------
    # Insert with duplicate protection
    # ----------------------------
    try:
        await db["notifications"].insert_one(notification_doc)
        print("✅ Notification stored")

    except DuplicateKeyError:
        # Happens when same action_id already inserted
        print("⚡ Duplicate webhook ignored:", action_id)

    except Exception as e:
        print("❌ Notification insert error:", e)


# ----------------------------
# Fetch notifications
# ----------------------------
@router.get("/trello/notifications/{user_id}")
async def get_notifications(user_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):

    notifications = await db["notifications"] \
        .find({"user_id": user_id}) \
        .sort("created_at", -1) \
        .to_list(100)

    unread_count = 0
    grouped = {}

    for n in notifications:
        n["_id"] = str(n["_id"])

        if not n.get("is_read"):
            unread_count += 1

        board_id = n.get("board_id", "unknown")
        board_name = n.get("board_name", "Untitled Board")

        grouped.setdefault(board_id, {
            "board_name": board_name,
            "notifications": []
        })

        grouped[board_id]["notifications"].append(n)

    return {
        "status": "success",
        "unread_count": unread_count,
        "notifications_by_board": grouped
    }


# ----------------------------
# Mark notification as read
# ----------------------------
@router.post("/notifications/mark-read/{notification_id}")
async def mark_notification_read(
    notification_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    result = await db["notifications"].update_one(
        {"_id": ObjectId(notification_id)},
        {"$set": {"is_read": True}}
    )

    return {
        "status": "success",
        "modified_count": result.modified_count
    }


# ----------------------------
# Get documents for board
# ----------------------------
@router.get("/board/{user_id}/{board_id}/docs")
async def get_board_docs(
    user_id: str,
    board_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    docs = await db["generated_docs"].find({
        "user_id": user_id,
        "board_id": board_id
    }).to_list(50)

    for d in docs:
        d["_id"] = str(d["_id"])

    return {"status": "success", "documents": docs}


# ----------------------------
# Regenerate document
# ----------------------------
@router.post("/regenerate-doc")
async def regenerate_doc(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    body = await request.json()

    user_id = body.get("user_id")
    board_id = body.get("board_id")
    doc_ids = body.get("doc_ids", [])

    if not user_id or not board_id or not doc_ids:
        return {"status": "error", "message": "Missing parameters"}

    new_docs = []

    for doc_id in doc_ids:
        doc = await db["generated_docs"].find_one({"_id": ObjectId(doc_id)})
        if not doc:
            continue

        new_doc = doc.copy()
        new_doc["_id"] = ObjectId()
        new_doc["version"] = doc.get("version", 1) + 1
        new_doc["created_at"] = datetime.utcnow()

        await db["generated_docs"].insert_one(new_doc)
        new_docs.append(str(new_doc["_id"]))

    return {"status": "success", "new_doc_ids": new_docs}

