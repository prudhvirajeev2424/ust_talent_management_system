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
from utils.file_upload_utils import logger

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
    logger.info(f"Fetching HM employees for HM ID: {hm_id}")
    try:
        job_rr = await resouce_request_col.find_one({"hm_id": hm_id})
        if not job_rr:
            logger.warning(f"No job records found for HM ID: {hm_id}.")
            return {"message": f"No job records found for HM ID: {hm_id}."}

        job_rr_id = str(job_rr.get("resource_request_id"))

        allocated_apps = await app_col.find({"job_rr_id": job_rr_id, "status": "Allocated"}).to_list(length=100)

        if not allocated_apps:
            logger.warning(f"No applications found for job RR ID: {job_rr_id} with 'Allocated' status.")
            return {"message": "No applications found for this job in 'Allocated' status."}

        unique_employee_ids = set(int(app["employee_id"]) for app in allocated_apps)

        employees_data = await emp_col.find({"employee_id": {"$in": list(unique_employee_ids)}}).to_list(length=100)

        if not employees_data:
            logger.warning(f"No employee data found for the allocated employees.")
            return {"message": "No employee data found for the allocated employees."}

        for emp in employees_data:
            emp["id"] = str(emp.get("_id"))
            emp.pop("_id", None)

        logger.info(f"Successfully fetched {len(employees_data)} employees for HM ID: {hm_id}.")
        return employees_data

    except Exception as e:
        logger.error(f"Error fetching HM employees for HM ID {hm_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching data: {str(e)}")

# ---------------- WFM Endpoint (only WFM role allowed) ----------------
@wfm_router.get("/{wfm_id}")
async def wfm_view(
    wfm_id: str,
    current_user: Dict[str, Any] = Depends(role_guard("WFM"))
):
    logger.info(f"Fetching WFM jobs for WFM ID: {wfm_id}")
    try:
        wfm_jobs = await resouce_request_col.find({"wfm_id": wfm_id}).to_list(length=100)
        if not wfm_jobs:
            logger.warning(f"No jobs found for WFM ID: {wfm_id}.")
            return {"message": f"No jobs found for WFM ID: {wfm_id}."}

        job_rr_ids = [str(job["resource_request_id"]) for job in wfm_jobs if job.get("resource_request_id")]

        if not job_rr_ids:
            logger.warning(f"No valid resource request IDs found for WFM ID: {wfm_id}.")
            return {"message": "No valid resource request IDs found for this WFM ID."}

        apps = await app_col.find({"job_rr_id": {"$in": job_rr_ids}}, {"employee_id": 1}).to_list(length=100)
        if not apps:
            logger.warning(f"No applications found for the given WFM jobs.")
            return {"message": "No applications found for these jobs."}

        emp_ids = {int(app["employee_id"]) for app in apps if app.get("employee_id")}

        if not emp_ids:
            logger.warning(f"No valid employee IDs found in the applications.")
            return {"message": "No valid employee IDs found in the applications."}

        result = await emp_col.find({"employee_id": {"$in": list(emp_ids)}}).to_list(length=100)

        if not result:
            logger.warning(f"No employee data found for the applications.")
            return {"message": "No employee data found for the applications."}

        for r in result:
            r["id"] = str(r.get("_id"))
            r.pop("_id", None)

        logger.info(f"Successfully fetched {len(result)} employees for WFM ID: {wfm_id}.")
        return result

    except Exception as e:
        logger.error(f"Error fetching WFM employees for WFM ID {wfm_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching data: {str(e)}")

# ---------------- TP Endpoint (only TP Manager role allowed) ----------------
@tp_router.get("/application_employees")
async def get_employees_from_applications(current_user: Dict[str, Any] = Depends(role_guard("TP Manager"))):
    logger.info("Fetching TP employees from applications.")
    try:
        apps = await app_col.find({}, {"employee_id": 1}).to_list(length=100)
        if not apps:
            logger.warning("No applications found.")
            return {"message": "No applications found."}

        employee_ids = {int(app["employee_id"]) for app in apps if app.get("employee_id")}

        if not employee_ids:
            logger.warning("No valid employee IDs found in the applications.")
            return {"message": "No valid employee IDs found in the applications."}

        employees_data = await emp_col.find({
            "employee_id": {"$in": list(employee_ids)},
            "type": "TP"
        }).to_list(length=100)

        if not employees_data:
            logger.warning("No TP employees found for the given applications.")
            return {"message": "No TP employees found for the given applications."}

        for emp in employees_data:
            emp["id"] = str(emp.get("_id"))
            emp.pop("_id", None)

        logger.info(f"Successfully fetched {len(employees_data)} TP employees.")
        return employees_data

    except Exception as e:
        logger.error(f"Error fetching TP employees from applications: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching data: {str(e)}")

    
# ====================== SEARCH (FINAL - WITH EMPLOYEE TYPE) ======================
@router.get("/search")
async def search_employees(search: str = Query(..., min_length=1),
                            current_user: Dict[str, Any] = Depends(role_guard("Admin"))):
   
    query = {
        "$or": [
            {"employee_name": {"$regex": search, "$options": "i"}},
            {"designation": {"$regex": search, "$options": "i"}},
            {"primary_technology": {"$regex": search, "$options": "i"}},
            {"secondary_technology": {"$regex": search, "$options": "i"}},
 
            # Employee identifiers
            {"employee_id": {"$regex": search, "$options": "i"}},
           
            # Employee Type fields (both exist in your data)
            {"type": {"$regex": search, "$options": "i"}},           # e.g. "TP", "Non TP"
            {"employment_type": {"$regex": search, "$options": "i"}}, # e.g. "Employee"
 
            # Location & Grade
            {"city": {"$regex": search, "$options": "i"}},
            {"band": {"$regex": search, "$options": "i"}},
        ]
    }
 
    # Bonus: If search is a full number → also try exact Employee ID match (faster & accurate)
    if search.strip().isdigit():
        query["$or"].append({"employee_id": int(search)})
 
    cursor = employees.find(query)
    docs = await cursor.to_list(length=None)
    result = [_serialize(doc) for doc in docs]
 
    return {"count": len(result), "data": result}
 
 # ====================== FILTER ======================
@router.get("/filter")
async def filter_employees(
    employee_type: Optional[str] = Query(None, description="TP, Non TP"),
    employment_type: Optional[str] = Query(None, description="Employee, Contractor"),
    city: Optional[str] = Query(None, description="e.g. Bangalore, Chennai"),
    band: Optional[str] = Query(None, description="e.g. A3, B1"),
    designation: Optional[str] = Query(None, description="e.g. Tester III"),
    primary_tech: Optional[str] = Query(None, alias="primary", description="e.g. Java"),
    secondary_tech: Optional[str] = Query(None, alias="secondary", description="e.g. Angular"),
    current_user: Dict[str, Any] = Depends(role_guard("Admin"))
    
    ):
 
    query: Dict[str, Any] = {}
 
    if employee_type:
        query["type"] = {"$regex": f"^{employee_type}$", "$options": "i"}
    if employment_type:
        query["employment_type"] = {"$regex": f"^{employment_type}$", "$options": "i"}
    if city:
        query["city"] = {"$regex": city, "$options": "i"}
    if band:
        query["band"] = {"$regex": band, "$options": "i"}
    if designation:
        query["designation"] = {"$regex": designation, "$options": "i"}
    if primary_tech:
        query["primary_technology"] = {"$regex": primary_tech, "$options": "i"}
    if secondary_tech:
        query["secondary_technology"] = {"$regex": secondary_tech, "$options": "i"}
   
    cursor = employees.find(query)
    docs = await cursor.to_list(length=None)
    result = [_serialize(doc) for doc in docs]
 
    return {
        "count": len(result),
        "data": result,
        "applied_filters": {
            "employee_type": employee_type,
            "employment_type": employment_type,
            "city": city,
            "band": band,
            "designation": designation,
            "primary_tech": primary_tech,
            "secondary_tech": secondary_tech,
        }
    }
 
# ====================== SORT ======================
 
@router.get("/sort")
async def sort_employees(
    sort_by: str = Query(
        "employee_name",
        description="Field to sort by (case-insensitive)",
        regex="^(?i)(Employee Name|Employee ID|Designation|Band|City|Type)$"  # ← Magic here
    ),
    order: str = Query(
        "asc",
        description="asc or desc",
        regex="^(?i)(asc|desc)$"  # also accepts ASC, Desc, etc.
    ),current_user: Dict[str, Any] = Depends(role_guard("Admin"))
):
    """
    Sort by:
    - Employee Name
    - Employee ID
    - Designation
    - Band
    - City      ← works with city / City / CITY
    - Type      ← works with type / TYPE
    """
    sort_order = 1 if order.lower() == "asc" else -1
 
    # Normalize the field name to exact DB field
    field_map = {
        "employee_name": "employee_name",
        "employee_id": "employee_id",
        "designation": "designation",
        "band": "band",
        "city": "city",
        "type": "type",
    }
 
    normalized = sort_by.strip().lower()
    db_field = field_map.get(normalized, "employee_name")  # safe fallback
 
    cursor = employees.find().sort(db_field, sort_order)
    docs = await cursor.to_list(length=None)
    result = [_serialize(doc) for doc in docs]
 
    return {
        "count": len(result),
        "data": result,
        "sorted_by": db_field,
        "order": order.lower()
    }
 
 
 
# ====================== LIST ALL EMPLOYEES ======================
@router.get("/employees", response_model=List[Dict[str, Any]])
async def get_employees(current_user: Dict[str, Any] = Depends(role_guard("Admin"))):
    try:
        employees_list = await fetch_all_employees()
        return employees_list
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching employees: {str(e)}"
        )
# ====================== GET SINGLE EMPLOYEE ======================
@router.get("/{employee_id}", response_model=Dict[str, Any])
async def get_employee(employee_id: int,current_user: Dict[str, Any] = Depends(role_guard("Admin"))):
    try:
        emp = await fetch_employee_by_id(employee_id)
        if not emp:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Employee not found"
            )
        return emp
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching employee: {str(e)}"
        )
       


# ====================== RESUME DOWNLOAD - ONLY OWN RESUME ======================
@router.get("/my-resume")  # ← New clean endpoint
async def get_my_resume(
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    employee_id = current_user.get("employee_id")
    if not employee_id:
        raise HTTPException(status_code=401, detail="Invalid user session")

    try:
        employee = await employees.find_one(
            {"employee_id": int(employee_id)},
            {"resume_file_id": 1, "resume": 1, "employee_name": 1}
        )
        if not employee:
            raise HTTPException(status_code=404, detail="Your profile not found")

        file_id = None
        filename = f"Resume_{employee_id}_{employee.get('employee_name', 'Employee')}.pdf".replace(" ", "_")

        # Try new field first
        if employee.get("resume_file_id"):
            try:
                oid = ObjectId(employee["resume_file_id"])
                if get_gridfs().get(oid):
                    file_id = oid
                    filename = employee.get("resume") or filename
            except:
                pass

        # Fallback to old field (legacy support)
        if not file_id and employee.get("resume"):
            val = employee["resume"]
            if isinstance(val, (str, ObjectId)) and ObjectId.is_valid(str(val)):
                try:
                    oid = ObjectId(str(val))
                    if get_gridfs().get(oid):
                        file_id = oid
                except:
                    pass

        if not file_id:
            raise HTTPException(status_code=404, detail="You have not uploaded a resume yet")

        grid_out = get_gridfs().get(file_id)
        file_data = grid_out.read()
        final_filename = grid_out.filename or filename

        mime_type, _ = mimetypes.guess_type(final_filename)
        if not mime_type:
            mime_type = "application/pdf"

        return Response(
            content=file_data,
            media_type=mime_type,
            headers={
                "Content-Disposition": f'attachment; filename="{final_filename}"',
                "Content-Length": str(grid_out.length),
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"[MY-RESUME ERROR] Employee {employee_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to download your resume")
    
     
 


# ====================== RESUME UPLOAD & PARSING ======================    
 
def clean_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)

@resume_router.put("/upload")  # ← Removed {employee_id} from path
async def upload_resume(
    file: UploadFile = File(...),
    current_user: Dict[str, Any] = Depends(get_current_user)  # This gives us the logged-in user
):
    logger.info(f"Uploading resume for employee ID: {current_user.get('employee_id')}")
    employee_id = current_user.get("employee_id")  # Extract from token
    if not employee_id:
        logger.error("Invalid user session.")
        raise HTTPException(status_code=401, detail="Invalid user session")

    existing_employee = await employees.find_one({"employee_id": int(employee_id)})
    if existing_employee and existing_employee.get("resume"):
        logger.info("Resume already uploaded for this user.")
        return {
            "message": "Your resume is already uploaded. You can upload a new one if you'd like."
        }

    allowed_types = [
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ]

    if file.content_type not in allowed_types:
        logger.error(f"Invalid file type uploaded: {file.content_type}")
        raise HTTPException(status_code=400, detail="Only PDF, DOC, and DOCX files are allowed")

    file_bytes = await file.read()
    if not file_bytes:
        logger.error("Uploaded file is empty.")
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        file_id = save_to_gridfs(file.filename, file_bytes)
        logger.info(f"File saved to GridFS with file_id: {file_id}")
    except Exception as e:
        logger.error(f"Error saving file: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error saving file: {str(e)}")

    try:
        raw_text = extract_text_from_bytes(file_bytes, file.filename)
        extracted_text = clean_text(raw_text) if 'clean_text' in globals() else raw_text.strip()
        logger.debug(f"Extracted text from resume: {extracted_text[:200]}...")  # log a snippet of the text
    except Exception as e:
        logger.error(f"Text extraction failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Text extraction failed: {str(e)}")

    parsed_resume = None
    try:
        parsed_resume = await parse_resume_with_llm(extracted_text)
        logger.info("LLM parsing successful.")
    except Exception as e:
        logger.warning(f"LLM parsing failed (continuing): {e}")

    update_body = {
        "resume": file_id,
        "resume_text": parsed_resume or extracted_text,
    }

    result = await employees.update_one(
        {"employee_id": int(employee_id)},
        {"$set": update_body}
    )

    if result.matched_count == 0:
        logger.error(f"Profile not found for employee ID: {employee_id}")
        raise HTTPException(status_code=404, detail="Your profile not found")

    logger.info(f"Resume uploaded successfully for employee ID: {employee_id}")
    return {
        "message": "Your resume has been uploaded and processed successfully!",
        "filename": file.filename,
        "file_id": str(file_id),
        "raw_text_length": len(extracted_text),
        "llm_parsed": bool(parsed_resume),
    }
