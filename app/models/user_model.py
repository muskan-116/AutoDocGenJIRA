# app/models/user_model.py
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, Dict, Any
from datetime import datetime
from bson.objectid import ObjectId

# Simple Pydantic model used for validation/payloads
class UserCreate(BaseModel):
    email: EmailStr
    name: Optional[str] = None
    password: Optional[str] = None

class UserOut(BaseModel):
    id: str = Field(..., alias="_id")
    email: EmailStr
    name: Optional[str] = None
    providers: Optional[Dict[str, Any]] = {}
    createdAt: Optional[datetime] = None

# Helper functions for DB access (used by route handlers)
def user_collection(app):
    return app.state.db.get_collection("users")

async def find_user_by_email(app, email: str):
    coll = user_collection(app)
    doc = await coll.find_one({"email": email})
    return doc

async def find_user_by_id(app, user_id: str):
    coll = user_collection(app)
    # allow both ObjectId and string id
    try:
        oid = ObjectId(user_id)
        doc = await coll.find_one({"_id": oid})
    except Exception:
        doc = await coll.find_one({"_id": user_id})
    return doc

async def create_user(app, user_doc: dict):
    coll = user_collection(app)
    result = await coll.insert_one(user_doc)
    return await coll.find_one({"_id": result.inserted_id})

async def update_user_by_id(app, user_id: str, update: dict):
    coll = user_collection(app)
    try:
        oid = ObjectId(user_id)
        await coll.update_one({"_id": oid}, {"$set": update})
    except Exception:
        await coll.update_one({"_id": user_id}, {"$set": update})
    return await find_user_by_id(app, user_id)
