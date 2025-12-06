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
                {"job_rr_id": {"$in": job_rr_ids}, "status": {"$nin": ["Draft", "Allocated","Rejected", "Selected","Withdrawn"]}},
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

@manager_router.patch("/applications/{app_id}/shortlist")
async def shortlist(app_id: str, current_user: dict = Depends(get_current_user)):
    app = await collections["applications"].find_one({"_id": app_id})
    if not app:
        raise HTTPException(404, "Application not found")
    if app["status"] != "Submitted":
        raise HTTPException(400, f"Cannot shortlist: application is in '{app['status']}' status")
   
    employee_id_str = app.get("employee_id")
    if not employee_id_str:
        raise HTTPException(400, "Application missing employee_id")
   
    emp = await get_employee_safely(employee_id_str)
    emp_type = emp.get("type", "Unknown")
 
    if current_user["role"] == "TP Manager" and emp_type == "TP":
        result = await collections["applications"].update_one(
            {"_id": app_id},
            {"$set": {
                "status": "Shortlisted",
                "shortlisted_by": current_user["employee_id"],
                "shortlisted_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }}
        )
        if result.modified_count:
            await log_audit("shortlist_tp", app_id, current_user["employee_id"])
            await update_job_stats_and_employee_type(app_id)
        return {"message": "Shortlisted by TP Manager"}
 
    elif current_user["role"] == "WFM" and emp_type == "Non TP":
        if not await verify_job_ownership(app["job_rr_id"], current_user["employee_id"], "WFM"):
            raise HTTPException(403, "You don't manage this job")
        result = await collections["applications"].update_one(
            {"_id": app_id},
            {"$set": {
                "status": "Shortlisted",
                "shortlisted_by": current_user["employee_id"],
                "shortlisted_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }}
        )
        if result.modified_count:
            await log_audit("shortlist_non_tp", app_id, current_user["employee_id"])
            await update_job_stats_and_employee_type(app_id)
        return {"message": "Shortlisted by WFM"}
 
    raise HTTPException(403, f"Cannot shortlist: {current_user['role']} cannot shortlist {emp_type} employees")
 

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

@manager_router.patch("/applications/{app_id}/select")
async def select_candidate(app_id: str, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "WFM":
        raise HTTPException(403, "Only WFM can select candidates")
   
    app = await collections["applications"].find_one({"_id": app_id})
    if not app:
        raise HTTPException(404, "Application not found")
    if app["status"] != "Interview":
        raise HTTPException(400, f"Cannot select: application is in '{app['status']}' status. Must be 'Interview'.")
   
    if not await verify_job_ownership(app["job_rr_id"], current_user["employee_id"], "WFM"):
        raise HTTPException(403, "You don't manage this job")
   
   
    result = await collections["applications"].update_one(
        {"_id": app_id},
        {"$set": {
            "status": "Selected",
            "selected_by": current_user["employee_id"],
            "selected_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }}
    )
   
    if result.modified_count:
        await log_audit("select_candidate", app_id, current_user["employee_id"])
        await update_job_stats_and_employee_type(app_id)
        return {"message": "Candidate Selected"}
   
    raise HTTPException(500, "Failed to select candidate")

@manager_router.patch("/applications/{app_id}/reject")
async def reject_candidate(
    app_id: str,
    reason: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user)
):
    if current_user["role"] != "WFM":
        raise HTTPException(403, "Only WFM can reject candidates")
   
    app = await collections["applications"].find_one({"_id": app_id})
    if not app:
        raise HTTPException(404, "Application not found")
   
    if not await verify_job_ownership(app["job_rr_id"], current_user["employee_id"], "WFM"):
        raise HTTPException(403, "You don't manage this job")
   
    if app["status"] == "Allocated":
        raise HTTPException(400, "Cannot reject: candidate is already allocated")
    if app["status"] == "Selected":
        raise HTTPException(400, "Cannot reject: candidate is selected. Contact HM to deallocate first.")
   
    result = await collections["applications"].update_one(
        {"_id": app_id},
        {"$set": {
            "status": "Rejected",
            "rejected_by": current_user["employee_id"],
            "rejected_at": datetime.utcnow(),
            "rejection_reason": reason,
            "updated_at": datetime.utcnow()
        }}
    )
   
    if result.modified_count:
        await log_audit("reject_candidate", app_id, current_user["employee_id"], {"reason": reason})
        await update_job_stats_and_employee_type(app_id)
        return {"message": "Candidate Rejected"}
   
    raise HTTPException(500, "Failed to reject candidate")

@manager_router.patch("/applications/{app_id}/allocate")
async def allocate(app_id: str, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "HM":
        raise HTTPException(403, "Only HM can allocate resources")
   
    app = await collections["applications"].find_one({"_id": app_id})
    if not app:
        raise HTTPException(404, "Application not found")
    if app["status"] != "Selected":
        raise HTTPException(400, f"Cannot allocate: application is in '{app['status']}' status. Must be 'Selected'.")
   
    job = await collections["resource_request"].find_one({
        "resource_request_id": app["job_rr_id"],
        "hm_id": current_user["employee_id"]
    })
    if not job:
        raise HTTPException(403, "You are not the Hiring Manager for this job")
   
    if await check_duplicate_allocation(app["employee_id"]):
        raise HTTPException(400, "Employee is already allocated to another project")
 
    result = await collections["applications"].update_one(
        {"_id": app_id},
        {"$set": {
            "status": "Allocated",
            "allocated_by": current_user["employee_id"],
            "allocated_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }}
    )
   
    if result.modified_count:
        await log_audit("allocate_candidate", app_id, current_user["employee_id"])
        await update_job_stats_and_employee_type(app_id)
        return {"message": "Allocated Successfully"}
   
    raise HTTPException(500, "Failed to allocate candidate")
 
@manager_router.patch("/bulk/applications/{action}")
async def bulk_manual_action(
    action: Literal["shortlist", "select", "reject", "allocate"],
    app_ids: List[str] = Query(...),
    current_user: dict = Depends(get_current_user)
):
    if not app_ids:
        raise HTTPException(400, "No application IDs provided")
    if len(app_ids) > 100:
        raise HTTPException(400, "Maximum 100 applications per bulk operation")
 
    allowed = {
        "TP Manager": {"shortlist"},
        "WFM": {"shortlist", "select", "reject"},
        "HM": {"allocate"},
        "Admin": {"shortlist", "select", "reject", "allocate"}
    }
   
    if action not in allowed.get(current_user["role"], set()):
        raise HTTPException(403, f"Role '{current_user['role']}' cannot perform '{action}' action")
 
    results = []
    for app_id in app_ids:
        try:
            if action == "shortlist":
                resp = await shortlist(app_id, current_user)
            elif action == "select":
                resp = await select_candidate(app_id, current_user)
            elif action == "reject":
                resp = await reject_candidate(app_id, current_user)
            elif action == "allocate":
                resp = await allocate(app_id, current_user)
           
            results.append({"app_id": app_id, "status": "success", "message": resp["message"]})
        except HTTPException as e:
            results.append({"app_id": app_id, "status": "failed", "error": str(e.detail)})
        except Exception as e:
            results.append({"app_id": app_id, "status": "failed", "error": f"Unexpected error: {str(e)}"})
 
    return {
        "action": action,
        "total": len(app_ids),
        "successful": len([r for r in results if r["status"] == "success"]),
        "failed": len([r for r in results if r["status"] == "failed"]),
        "results": results
    }
 
@manager_router.get("/skill-matches/applications/{job_rr_id}")
async def get_skill_matches(
    job_rr_id: str,
    min_match: Optional[float] = Query(None, ge=0.0, le=100.0),
    current_user: dict = Depends(get_current_user)
):
    job = await collections["resource_request"].find_one({"resource_request_id": job_rr_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job RR not found")
   
    role = current_user["role"]
    emp_id = current_user["employee_id"]
   
    if role == "WFM" and job.get("wfm_id") != emp_id:
        raise HTTPException(403, "You don't manage this job")
    elif role == "HM" and job.get("hm_id") != emp_id:
        raise HTTPException(403, "You are not the Hiring Manager for this job")
    elif role not in ["WFM", "HM", "Admin"]:
        raise HTTPException(403, "Unauthorized to view skill matches")
 
    required_skills = job.get("mandatory_skills", [])
    if not required_skills:
        return {"message": "No required skills defined for this job"}
 
    parsed_skills = []
    for skill in required_skills:
        skill_str = str(skill).strip("[]'\"")
        if ',' in skill_str:
            parsed_skills.extend([s.strip().strip("'\"") for s in skill_str.split(',')])
        else:
            parsed_skills.append(skill_str.strip())
    
    req_skills = {skill.strip().lower() for skill in parsed_skills if skill.strip()}
 
    pipeline = [
        {"$match": {"job_rr_id": job_rr_id, "status": "Submitted"}},
        {"$addFields": {"employee_id_int": {"$toInt": "$employee_id"}}},
        {"$lookup": {
            "from": "employees",
            "localField": "employee_id_int",
            "foreignField": "employee_id",
            "as": "employee_data"
        }},
        {"$unwind": {"path": "$employee_data", "preserveNullAndEmptyArrays": True}},
        {"$project": {
            "_id": 1,
            "employee_id": 1,
            "employee_name": "$employee_data.employee_name",
            "designation": "$employee_data.designation",
            "city": "$employee_data.city",
            "skills": "$employee_data.detailed_skills"
        }}
    ]
   
    applications = await collections["applications"].aggregate(pipeline).to_list(1000)
 
    results = []
    for app in applications:
        if not app.get("employee_name"):
            continue
 
        emp_skills_raw = app.get("skills") or []
        if isinstance(emp_skills_raw, str):
            emp_skills_raw = [emp_skills_raw]
        
        emp_skills = {skill.strip().lower() for skill in emp_skills_raw if skill}
        
        matched_count = len(emp_skills.intersection(req_skills))
        match_percentage = (matched_count / len(req_skills)) * 100 if req_skills else 0
 
        if min_match is not None and match_percentage < min_match:
            continue
 
        results.append({
            "application_id": str(app["_id"]),
            "employee_id": app["employee_id"],
            "employee_name": app.get("employee_name", "Unknown"),
            "current_designation": app.get("designation"),
            "location": app.get("city"),
            "match_percentage": round(match_percentage, 2),
            "matched_skills": sorted(list(emp_skills.intersection(req_skills))),
            "missing_skills": sorted(list(req_skills - emp_skills)),
            "total_required_skills": len(req_skills),
            "skills_matched_count": matched_count
        })
 
    results.sort(key=lambda x: x["match_percentage"], reverse=True)
 
    return {
        "job_rr_id": job_rr_id,
        "job_title": job.get("ust_role"),
        "total_applications": len(applications),
        "candidates_returned": len(results),
        "required_skills": sorted(list(req_skills)),
        "min_match_filter_applied": min_match,
        "candidates": results
    }