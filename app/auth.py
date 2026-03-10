import secrets
from fastapi import Header, HTTPException
from app.config import TOKEN_BYTES
from app.database import get_db


def generate_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


async def get_current_agent(authorization: str = Header(...)) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Invalid authorization header")
    token = authorization[7:]
    db = get_db()
    row = await db.execute_fetchall(
        "SELECT id, name, status FROM agents WHERE auth_token = ?", (token,)
    )
    if not row:
        raise HTTPException(401, "Invalid token")
    agent = row[0]
    return {"id": agent["id"], "name": agent["name"], "status": agent["status"]}
