from fastapi import APIRouter, Depends, HTTPException, Query
from database import collections
from utils.security import get_current_user
from datetime import datetime
from typing import List, Literal, Optional

manager_router = APIRouter(prefix="/api/manager", tags=["Manager Workflow"])

async def log_audit(action: str, app_id: str, performed_by: str, details: dict = None):
    try:
        user = await collections["users"].find_one({"employee_id": performed_by}, {"role": 1})
        await collections["audit_logs"].insert_one({
            "action": action,
            "application_id": app_id,
            "performed_by": performed_by,
            "performed_by_role": user["role"] if user else "Unknown",
            "details": details or {},
            "timestamp": datetime.utcnow()
        })
    except Exception as e:
        print(f"Audit log failed: {e}")

def safe_int_conversion(employee_id_str: str) -> int:
    try:
        return int(employee_id_str)
    except (ValueError, TypeError):
        raise HTTPException(400, f"Invalid employee_id format: {employee_id_str}")

async def get_employee_safely(employee_id_str: str) -> dict:
    employee = await collections["employees"].find_one({
        "$or": [
            {"employee_id": employee_id_str},
            {"employee_id": safe_int_conversion(employee_id_str)}
        ]
    })
    if not employee:
        raise HTTPException(404, f"Employee not found: {employee_id_str}")
    return employee

async def check_duplicate_allocation(employee_id_str: str) -> bool:
    existing = await collections["applications"].find_one({
        "employee_id": employee_id_str,
        "status": "Allocated"
    })
    return existing is not None


async def verify_job_ownership(job_rr_id: str, employee_id: str, role: str) -> bool:
    ownership_field = {"WFM": "wfm_id", "HM": "hm_id"}.get(role)
    if not ownership_field:
        return False
    job = await collections["resource_request"].find_one({
        "resource_request_id": job_rr_id,
        ownership_field: employee_id
    })
    return job is not None

async def update_job_stats_and_employee_type(app_id: str):
    app = await collections["applications"].find_one({"_id": app_id})
    if not app:
        return
    
    job_rr_id = app.get("job_rr_id")
    employee_id_str = app.get("employee_id")
    if not job_rr_id or not employee_id_str:
        return

    pipeline = [
        {"$match": {"job_rr_id": job_rr_id}},
        {"$group": {"_id": "$status", "count": {"$sum": 1}}}
    ]
    stats = {item["_id"]: item["count"] async for item in collections["applications"].aggregate(pipeline)}

    interview_stats = await collections["applications"].aggregate([
        {"$match": {"job_rr_id": job_rr_id, "status": "Interview"}},
        {"$group": {"_id": "$interview_type", "count": {"$sum": 1}}}
    ]).to_list(10)

    internal_interview = next((x["count"] for x in interview_stats if x["_id"] == "internal"), 0)
    customer_interview = next((x["count"] for x in interview_stats if x["_id"] == "customer"), 0)

    update_data = {
        "resources_in_propose": stats.get("Shortlisted", 0),
        "resources_in_internal_interview": internal_interview,
        "resources_in_customer_interview": customer_interview,
        "resources_in_hm_check": stats.get("Selected", 0),
        "resources_in_allocated": stats.get("Allocated", 0),
        "resources_in_reject": stats.get("Rejected", 0),
        "resources_in_not_allocated": stats.get("Shortlisted", 0) + stats.get("Interview", 0) + stats.get("Selected", 0),
        "resources_in_accept": stats.get("Selected", 0),
        "last_updated": datetime.utcnow(),
        "last_updated_by": "workflow_engine"
    }

    await collections["resource_request"].update_one(
        {"resource_request_id": job_rr_id},
        {"$set": update_data}
    )

    if app["status"] == "Allocated":
        employee = await collections["employees"].find_one({
            "$or": [
                {"employee_id": employee_id_str},
                {"employee_id": safe_int_conversion(employee_id_str)}
            ]
        })
        
        if employee:
            old_type = employee.get("type", "Unknown")
            result = await collections["employees"].update_one(
                {"_id": employee["_id"]},
                {"$set": {"type": "Non TP", "updated_at": datetime.utcnow()}}
            )
            if result.modified_count:
                await log_audit("employee_type_changed", app_id, "system", {
                    "employee_id": employee_id_str,
                    "from": old_type,
                    "to": "Non TP",
                    "reason": "Allocated to project"
                })
        else:
            await log_audit("employee_type_change_failed", app_id, "system", {
                "employee_id": employee_id_str,
                "error": "Employee record not found for type update"
            })

async def get_manager_applications(current_user: dict, page: int = 1, limit: int = 50):
    role = current_user["role"]
    emp_id = current_user["employee_id"]
    skip = (page - 1) * limit

    if role == "TP Manager":
        tp_emp_ids = [str(e["employee_id"]) async for e in collections["employees"].find({"type": "TP"}, {"employee_id": 1})]
        query = {"employee_id": {"$in": tp_emp_ids}, "status": "Submitted"}

    elif role == "WFM":
        job_rr_ids = [j["resource_request_id"] async for j in collections["resource_request"].find({"wfm_id": emp_id}, {"resource_request_id": 1})]
        if not job_rr_ids:
            return {"applications": [], "total": 0, "page": page, "limit": limit}

        non_tp_emp_ids = [str(e["employee_id"]) async for e in collections["employees"].find({"type": "Non TP"}, {"employee_id": 1})]
        query = {
            "$or": [
                {"job_rr_id": {"$in": job_rr_ids}, "status": {"$nin": ["Draft", "Allocated"]}},
                {"job_rr_id": {"$in": job_rr_ids}, "employee_id": {"$in": non_tp_emp_ids}, "status": "Submitted"}
            ]
        }

    elif role == "HM":
        job_rr_ids = [j["resource_request_id"] async for j in collections["resource_request"].find({"hm_id": emp_id}, {"resource_request_id": 1})]
        if not job_rr_ids:
            return {"applications": [], "total": 0, "page": page, "limit": limit}
        query = {"job_rr_id": {"$in": job_rr_ids}, "status": "Selected"}

    else:
        raise HTTPException(status_code=403, detail="Unauthorized role")

    total = await collections["applications"].count_documents(query)
    cursor = collections["applications"].find(query).sort("updated_at", -1).skip(skip).limit(limit)
    applications = await cursor.to_list(limit)
    
    return {
        "applications": applications,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit
    }

@manager_router.get("/applications")
async def list_applications(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user)
):
    return await get_manager_applications(current_user, page, limit)

@manager_router.patch("/applications/{app_id}/interview")
async def to_interview(
    app_id: str,
    interview_type: Literal["internal", "customer"] = Query(...),
    current_user: dict = Depends(get_current_user)
):
    if current_user["role"] != "WFM":
        raise HTTPException(403, "Only WFM can schedule interviews")
 
    app = await collections["applications"].find_one({"_id": app_id})
    if not app:
        raise HTTPException(404, "Application not found")
   
    if not await verify_job_ownership(app["job_rr_id"], current_user["employee_id"], "WFM"):
        raise HTTPException(403, "You don't manage this job")
 
    if app["status"] not in ["Shortlisted", "Interview"]:
        raise HTTPException(400, f"Cannot schedule interview: current status is '{app['status']}'. Must be 'Shortlisted' first.")
 
    result = await collections["applications"].update_one(
        {"_id": app_id},
        {"$set": {
            "status": "Interview",
            "interview_type": interview_type,
            "interview_scheduled_by": current_user["employee_id"],
            "interview_scheduled_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }}
    )
 
    if result.modified_count:
        await log_audit("move_to_interview", app_id, current_user["employee_id"],
                       {"interview_type": interview_type, "previous_status": app["status"]})
        await update_job_stats_and_employee_type(app_id)
        return {"message": f"Moved to {interview_type.title()} Interview", "previous_status": app["status"]}
 
    raise HTTPException(500, "Failed to update application")