from datetime import datetime, timezone
from database import collections

async def log_employee_activity(user: dict, action: str, details: dict = None):
    entry = {
        "employee_id": user["employee_id"],
        "role": user["role"],
        "action": action,
        "details": details or {},
        "timestamp": datetime.now(timezone.utc)
    }
    await collections["admin_logs"].insert_one(entry)
