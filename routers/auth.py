from fastapi import APIRouter, HTTPException, Depends
from jose import JWTError, jwt, ExpiredSignatureError
from datetime import timedelta, datetime, timezone
from fastapi.security import HTTPBearer
from database import collections
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

# Login endpoint: Allows a user to log in with username and password
@router.post("/login")
async def login(username: str, password: str):
    # Find the user by employee_id (username)
    user = await collections["users"].find_one({"employee_id": username})
    
    # If user not found or password is invalid, raise an HTTP exception
    if not user or not verify_password(password, user["password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Create an access token (JWT) for the user with employee_id and role
    access_token = create_access_token({"sub": user["employee_id"], "role": user["role"]})
    # Create a refresh token for the user
    refresh_token = create_refresh_token({"sub": user["employee_id"], "role": user["role"]})

    # Store the refresh token in the database with its expiration date
    await collections["refresh_tokens"].insert_one({
        "token": refresh_token,
        "employee_id": user["employee_id"],
        "created_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc) + timedelta(days=7)  # Refresh token valid for 7 days
    })

    # Return the generated tokens and their expiration info
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",  # JWT bearer token type
        "expires_in": "300 seconds"  # Access token expiration time
    }

# Refresh endpoint: Allows the user to refresh their access token using a valid refresh token
@router.post("/refresh")
async def refresh_token(refresh_token: str):
    try:
        # Decode the refresh token to extract payload and verify its validity
        payload = jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
        emp_id = payload.get("sub")  # Extract employee_id from payload
        token_type = payload.get("type")  # Extract token type (should be "refresh")

        # If the token is not a refresh token, raise an error
        if token_type != "refresh":
            raise HTTPException(status_code=401, detail="Invalid refresh token")

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
        {"employee_id": emp_id}, sort=[("created_at", -1)]
    )
    if last_token:
        await collections["refresh_tokens"].delete_one({"_id": last_token["_id"]})

    # Insert the new refresh token into the database with expiration time
    await collections["refresh_tokens"].insert_one({
        "token": new_refresh_token,
        "employee_id": emp_id,
        "created_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc) + timedelta(days=7)
    })

    # Return the new access token and refresh token information
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
