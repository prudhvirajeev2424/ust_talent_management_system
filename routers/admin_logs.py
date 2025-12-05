from fastapi import APIRouter, Depends, HTTPException
from database import collections
from utils.security import get_current_user
from datetime import datetime,timezone
from utils.activity_logger import log_employee_activity

router = APIRouter(prefix="/api/admin/activity", tags=["Admin Logs"])

# Helper: Only Admin allowed
async def require_admin(user: dict = Depends(get_current_user)):
    if user["role"] != "Admin":
        raise HTTPException(status_code=403, detail="Admin access only")
    return user

# === Helper to insert employee activity logs ===
async def log_employee_activity(user: dict, action: str, details: dict = None):
    entry = {
        "employee_id": user["employee_id"],
        "role": user["role"],
        "action": action,
        "details": details or {},
        "timestamp": datetime.now(timezone.utc)
    }
    await collections["admin_logs"].insert_one(entry)

# === Admin endpoint to view employee activity logs ===
@router.get("/")
async def get_employee_activity(admin=Depends(require_admin)):
    logs = await collections["admin_logs"].find().sort("timestamp", -1).to_list(500)
    # Convert ObjectId to string for safe JSON response
    for log in logs:
        log["_id"] = str(log["_id"])
    return logs
