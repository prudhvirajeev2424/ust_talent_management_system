from fastapi import APIRouter, HTTPException,Depends,Response
from typing import List, Dict, Any
from database import resource_request, applications, employees
from utils.security import get_current_user
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, status, Query
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, UploadFile, File
from utils.llm_service import parse_resume_with_llm
from database import employees,fs
from bson import ObjectId
import base64
from bson import ObjectId
from fastapi import Response, HTTPException
import mimetypes
 
from utils.employee_service import extract_text_from_bytes, save_to_gridfs
from utils.employee_service import (
    fetch_all_employees,
    fetch_employee_by_id,
    _serialize,              
)
from database import employees
from database import get_gridfs
 
resume_router = APIRouter(prefix="/resume")
router = APIRouter(prefix="/employees")
# Defining routers
hm_router = APIRouter(prefix="/hm")
wfm_router = APIRouter(prefix="/wfm")
tp_router = APIRouter(prefix="/tp")
 
 
 
# Directly refer to MongoDB collections (no need for function wrappers)
resouce_request_col=resource_request
app_col = applications
emp_col = employees
 
# --- Simple inline role guard factory (no new files) ---
def role_guard(required_role: str):
    """
    Dependency factory to enforce that current_user.role == required_role.
    Usage: Depends(role_guard("HM"))
    """
    async def _guard(current_user: Dict[str, Any] = Depends(get_current_user)):
        role = current_user.get("role")
        if role != required_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"User role '{role}' not authorized. Required role: '{required_role}'"
            )
        return current_user
    return _guard
 
# ---------------- HM Endpoint (only HM role allowed) ----------------
@hm_router.get("/{hm_id}")
async def get_hm_employees(
    hm_id: str,
    current_user: Dict[str, Any] = Depends(role_guard("HM"))
   
):
    try:
        # Get the job record using `hm_id`
        job_rr = await resouce_request_col.find_one({"hm_id": hm_id})
        if not job_rr:
            return {"message": f"No job records found for HM ID: {hm_id}."}
 
        job_rr_id = str(job_rr.get("resource_request_id"))
 
        # Get all applications for this job RR ID with status 'Allocated'
        allocated_apps = await app_col.find({"job_rr_id": job_rr_id, "status": "Allocated"}).to_list(length=100)
 
        if not allocated_apps:
            return {"message": "No applications found for this job in 'Allocated' status."}
 
        # Remove duplicates by converting the list of employee IDs to a set (for unique employee IDs)
        unique_employee_ids = set(int(app["employee_id"]) for app in allocated_apps)
 
        # Fetch employee data using the unique employee IDs
        employees_data = await emp_col.find({"employee_id": {"$in": list(unique_employee_ids)}}).to_list(length=100)
 
        if not employees_data:
            return {"message": "No employee data found for the allocated employees."}
 
        # Remove MongoDB internal `_id` field
        for emp in employees_data:
            emp["id"] = str(emp.get("_id"))
            emp.pop("_id", None)
 
        return employees_data
 
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching data: {str(e)}")
 
# ---------------- WFM Endpoint (only WFM role allowed) ----------------
@wfm_router.get("/{wfm_id}")
async def wfm_view(
    wfm_id: str,
    current_user: Dict[str, Any] = Depends(role_guard("WFM"))
):
    try:
        # Get the jobs for the given `wfm_id`
        wfm_jobs = await resouce_request_col.find({"wfm_id": wfm_id}).to_list(length=100)
        if not wfm_jobs:
            return {"message": f"No jobs found for WFM ID: {wfm_id}."}
 
        job_rr_ids = [str(job["resource_request_id"]) for job in wfm_jobs if job.get("resource_request_id")]
       
        if not job_rr_ids:
            return {"message": "No valid resource request IDs found for this WFM ID."}
 
        # Get applications for the job RR IDs
        apps = await app_col.find({"job_rr_id": {"$in": job_rr_ids}}, {"employee_id": 1}).to_list(length=100)
        if not apps:
            return {"message": "No applications found for these jobs."}
 
        # Extract unique employee IDs (convert to int and dedupe)
        emp_ids = {int(app["employee_id"]) for app in apps if app.get("employee_id")}
 
        if not emp_ids:
            return {"message": "No valid employee IDs found in the applications."}
 
        # Fetch employee data for the found employee IDs
        result = await emp_col.find({"employee_id": {"$in": list(emp_ids)}}).to_list(length=100)
 
        if not result:
            return {"message": "No employee data found for the applications."}
 
        # Remove MongoDB internal `_id` field
        for r in result:
            r["id"] = str(r.get("_id"))
            r.pop("_id", None)
 
        return result
 
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching data: {str(e)}")
 
# ---------------- TP Endpoint (only TP Manager role allowed) ----------------
@tp_router.get("/application_employees")
async def get_employees_from_applications(current_user: Dict[str, Any] = Depends(role_guard("TP Manager"))):
    try:
        # Get all applications and their employee IDs
        apps = await app_col.find({}, {"employee_id": 1}).to_list(length=100)
        if not apps:
            return {"message": "No applications found."}
 
        # Extract unique employee IDs (convert to int and dedupe)
        employee_ids = {int(app["employee_id"]) for app in apps if app.get("employee_id")}
 
        if not employee_ids:
            return {"message": "No valid employee IDs found in the applications."}
 
        # Fetch employees with the extracted IDs and filter by "Type" set to "TP"
        employees_data = await emp_col.find({
            "employee_id": {"$in": list(employee_ids)},
            "type": "TP"
        }).to_list(length=100)
 
        if not employees_data:
            return {"message": "No TP employees found for the given applications."}
        # Remove MongoDB internal `_id` field
        for emp in employees_data:
            emp["id"] = str(emp.get("_id"))
            emp.pop("_id", None)
 
        return employees_data
 
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching data: {str(e)}")
 
 
 