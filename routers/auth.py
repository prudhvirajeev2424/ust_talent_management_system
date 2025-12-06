from fastapi import APIRouter, HTTPException, Depends,Request
from jose import JWTError, jwt, ExpiredSignatureError
from datetime import timedelta, datetime, timezone
from fastapi.security import HTTPBearer
from database import collections
from passlib.context import CryptContext
from models import ForgotPasswordRequest,ResetPasswordRequest,verifyCodeRequest
import random
import string
from utils.activity_logger import log_employee_activity
from utils.security import (
    verify_password,        # Function to verify user password
    create_access_token,    # Function to create access token
    create_refresh_token,   # Function to create refresh token
    get_current_user,       # Dependency to get the current logged-in user
    SECRET_KEY,             # Secret key used for signing JWTs
    ALGORITHM               # Algorithm used for encoding JWTs
)

# Initialize the router for the auth endpoints
router = APIRouter(prefix="/api/auth", tags=["Auth"])
# Define the bearer authentication scheme
bearer_scheme = HTTPBearer()

@router.post("/login")
async def login(username: str, password: str, request:Request):
   
    # Verify user credentials
    user = await collections["users"].find_one({"employee_id": username})
    if not user or not verify_password(password, user["password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
   
    # Issue tokens
    access_token = create_access_token({"sub": user["employee_id"], "role": user["role"]})
    refresh_token = create_refresh_token({"sub": user["employee_id"], "role": user["role"]})
 
    await collections["refresh_tokens"].insert_one({
        "token": refresh_token,
        "employee_id": user["employee_id"],
        "created_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc) + timedelta(days=7)
    })
   
    await log_employee_activity(user, "login", {"ip": request.client.host})
 
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": 300
    }
 
 


# @router.post("/login")
# async def login(username: str, password: str, request:Request):
#     # Check if user is blocked
#     attempt = await collections["login_attempts"].find_one({"employee_id": username})
#     blocked_until = attempt.get("blocked_until") if attempt else None

#     # Normalize blocked_until to UTC-aware before comparing
#     if blocked_until:
#         if blocked_until.tzinfo is None:
#             blocked_until = blocked_until.replace(tzinfo=timezone.utc)

#         if blocked_until > datetime.now(timezone.utc):
#             raise HTTPException(
#                 status_code=403,
#                 detail="Account temporarily blocked. Try again later."
#             )

#     # Verify user credentials
#     user = await collections["users"].find_one({"employee_id": username})
#     if not user or not verify_password(password, user["password"]):
#         # Record failed attempt
#         if not attempt:
#             await collections["login_attempts"].insert_one({
#                 "employee_id": username,
#                 "failed_count": 1,
#                 "blocked_until": None,
#                 "last_attempt": datetime.now(timezone.utc)
#             })
#         else:
#             failed_count = attempt.get("failed_count", 0) + 1
#             blocked_until = None
#             if failed_count >= 3:
#                 blocked_until = datetime.now(timezone.utc) + timedelta(seconds=30)
#                 failed_count = 0  # reset after block
#             await collections["login_attempts"].update_one(
#                 {"employee_id": username},
#                 {"$set": {
#                     "failed_count": failed_count,
#                     "blocked_until": blocked_until,
#                     "last_attempt": datetime.now(timezone.utc)
#                 }}
#             )
#         raise HTTPException(status_code=401, detail="Invalid credentials")

#     # Reset attempts on successful login
#     await collections["login_attempts"].delete_one({"employee_id": username})

#     # Issue tokens
#     access_token = create_access_token({"sub": user["employee_id"], "role": user["role"]})
#     refresh_token = create_refresh_token({"sub": user["employee_id"], "role": user["role"]})

#     await collections["refresh_tokens"].insert_one({
#         "token": refresh_token,
#         "employee_id": user["employee_id"],
#         "created_at": datetime.now(timezone.utc),
#         "expires_at": datetime.now(timezone.utc) + timedelta(days=7)
#     })
    
#     await log_employee_activity(user, "login", {"ip": request.client.host})

#     return {
#         "access_token": access_token,
#         "refresh_token": refresh_token,
#         "token_type": "bearer",
#         "expires_in": 300
#     }
@router.post("/forgot-password")
async def forgot_password(request: ForgotPasswordRequest):
    user = await collections["users"].find_one({"email": request.email})
    if not user:
        raise HTTPException(status_code=404, detail="Email not registered")
 
    code = ''.join(random.choices(string.digits, k=6))
    expiry = datetime.now(timezone.utc) + timedelta(minutes=10)
 
    await collections["reset_collection"].update_one(
        {"email": request.email},
        {"$set": {"code": code, "expiry": expiry}},
        upsert=True
    )
 
    # Dummy "send email"
    print(f"Verification code for {request.email}: {code}")
 
    return {"message": "Verification code sent (check console for demo)"}
 
@router.post("/verify-code")
async def verify_code(request: verifyCodeRequest):
    token = await collections["reset_collection"].find_one({"email": request.email})
    if not token or token["code"] != request.code:
        raise HTTPException(status_code=400, detail="Invalid code")

    expiry = token["expiry"].replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expiry:
        raise HTTPException(status_code=400, detail="Code expired")

    await collections["reset_collection"].update_one(
        {"email": request.email},
        {"$set": {"verified": True}}
    )

    return {"message": "Code verified successfully"}

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
@router.post("/reset-password")
async def reset_password(request: ResetPasswordRequest):
    token = await collections["reset_collection"].find_one({"email": request.email})
    if not token or not token.get("verified"):
        raise HTTPException(status_code=400, detail="Code not verified")

    hashed_pw = pwd_context.hash(request.new_password)
    await collections["users"].update_one(
        {"email": request.email},
        {"$set": {"password": hashed_pw}}
    )

    await collections["reset_collection"].delete_one({"email": request.email})

    return {"message": "Password updated successfully"}

# Refresh endpoint: Allows the user to refresh their access token using a valid refresh token
@router.post("/refresh")
async def refresh_token(refresh_token: str):
    try:
        # Decode the refresh token to extract payload and verify its validity
        payload = jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
        emp_id = payload.get("sub")  
        token_type = payload.get("type")  # Extract token type (should be "refresh")

        # If the token is not a refresh token, raise an error
        if token_type != "refresh":
            raise HTTPException(status_code=401, detail="Wrong Refresh token")

        # Check if the refresh token exists in the database
        stored = await collections["refresh_tokens"].find_one({"token": refresh_token})
        if not stored:
            raise HTTPException(status_code=401, detail="Refresh token revoked")

    except ExpiredSignatureError:
        # Handle expired refresh token
        raise HTTPException(status_code=401, detail="Refresh token expired")
    except JWTError:
        # Handle invalid JWT token
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    # Find the user by employee_id from the decoded refresh token
    user = await collections["users"].find_one({"employee_id": emp_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Generate new access and refresh tokens
    new_access_token = create_access_token({"sub": emp_id, "role": user["role"]})
    new_refresh_token = create_refresh_token({"sub": emp_id, "role": user["role"]})

    # Delete the old refresh token to keep the latest valid one
    last_token = await collections["refresh_tokens"].find_one(
        #basically we are updating the refress token in descending order
        {"employee_id": emp_id}, sort=[("created_at", -1)]
    )
    #deleteing the latest token
    if last_token:
        await collections["refresh_tokens"].delete_one({"_id": last_token["_id"]})

    # Insert the new refresh token into the database with expiration time
    await collections["refresh_tokens"].insert_one({
        "token": new_refresh_token,
        "employee_id": emp_id,
        "created_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc) + timedelta(days=7)
    })

    # Return the new access token information
    return {
        "access_token": new_access_token,
        "token_type": "bearer",  # JWT bearer token type
        "expires_in": "300 seconds"  # Access token expiration time
    }

# Logout endpoint: Allows the user to log out by invalidating their refresh tokens
@router.post("/logout")
async def logout(current_user=Depends(get_current_user)):  # Get the current user using dependency
    # Find all refresh tokens for the current user
    tokens = collections["refresh_tokens"].find({"employee_id": current_user["employee_id"]})
    async for token in tokens:
        # Insert the token into a block list to invalidate it
        await collections["block_list_tokens"].insert_one({
            "token": token["token"],
            "employee_id": token["employee_id"],
            "blacklisted_at": datetime.now(timezone.utc)  # Log the time the token was blacklisted
        })
    
    # Delete all refresh tokens for the current user (effectively logging them out)
    await collections["refresh_tokens"].delete_many({"employee_id": current_user["employee_id"]})
    
    # Return a success message
    return {"message": "Logged out successfully"}
