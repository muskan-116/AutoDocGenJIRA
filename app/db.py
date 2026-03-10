# app/db.py
from fastapi import Request

# ✅ db.py sirf dependency provide karta hai
# MongoDB connection main.py ke startup mein hota hai — ek jagah, ek baar

async def get_db(request: Request):
    """
    FastAPI dependency — app.state.db return karta hai
    Jo main.py startup mein set hota hai
    """
    return request.app.state.db
