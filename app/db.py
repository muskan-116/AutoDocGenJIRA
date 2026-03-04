# app/db.py
from motor.motor_asyncio import AsyncIOMotorClient
import os

MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://hadiamoosa40_db_user:op6v4ma4mlzA75wF@users.cy4zf7c.mongodb.net/Doc_Gen?retryWrites=true&w=majority")
DB_NAME = os.getenv("DB_NAME", "Doc_Gen")

client = AsyncIOMotorClient(MONGO_URI)
db = client[DB_NAME]

# Dependency for FastAPI
async def get_db():
    return db
