# app/db.py
from motor.motor_asyncio import AsyncIOMotorClient
from fastapi import FastAPI
import os
import logging

logger = logging.getLogger(__name__)

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME", "Doc_Gen")

if not MONGO_URI:
    raise ValueError("❌ MONGO_URI environment variable is not set!")

client = AsyncIOMotorClient(MONGO_URI)
db = client[DB_NAME]

# ================= STARTUP INIT =================
async def init_db():
    """
    Run once on app startup:
    - Creates TTL index on oauth_states (auto-deletes expired states)
    - Verifies MongoDB connection
    """
    try:
        # ✅ Verify connection
        await client.admin.command("ping")
        logger.info("✅ MongoDB connected successfully")

        # ✅ TTL index — expired oauth states auto-delete honge
        await db["oauth_states"].create_index(
            "expires_at",
            expireAfterSeconds=0,
            name="oauth_states_ttl"
        )
        logger.info("✅ TTL index created on oauth_states")

        # ✅ Index on jira_tokens for fast lookup
        await db["jira_tokens"].create_index(
            "user_id",
            unique=True,
            name="jira_tokens_user_id"
        )
        logger.info("✅ Index created on jira_tokens.user_id")

    except Exception as e:
        logger.error(f"❌ MongoDB init failed: {e}")
        raise

# ================= DEPENDENCY =================
async def get_db():
    return db
