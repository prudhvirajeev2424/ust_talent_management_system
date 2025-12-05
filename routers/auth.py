from fastapi import APIRouter, HTTPException, Depends
from jose import JWTError, jwt, ExpiredSignatureError
from datetime import timedelta, datetime,timezone
from fastapi.security import HTTPBearer
from database import collections
from utils.security import (
    verify_password,
    create_access_token,
    create_refresh_token,
    get_current_user,
    SECRET_KEY,
    ALGORITHM
)

router = APIRouter(prefix="/api/auth", tags=["Auth"])
bearer_scheme = HTTPBearer()

@router.post("/login")
async def login(username: str, password: str):
    user = await collections["users"].find_one({"employee_id": username})
    if not user or not verify_password(password, user["password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    access_token = create_access_token({"sub": user["employee_id"], "role": user["role"]})
    refresh_token = create_refresh_token({"sub": user["employee_id"], "role": user["role"]})

    await collections["refresh_tokens"].insert_one({
        "token": refresh_token,
        "employee_id": user["employee_id"],
        "created_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc) + timedelta(days=7)
    })

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": "300 seconds"
    }