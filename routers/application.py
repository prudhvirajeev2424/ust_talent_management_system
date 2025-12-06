from fastapi import APIRouter, Depends, HTTPException,status,Query,UploadFile,Form,File,Request,UploadFile, File
from typing import List, Optional
from datetime import datetime,timezone
import uuid
from gridfs import GridFS,GridFSBucket
from pymongo.database import Database
from database import collections
from models import Application, ApplicationStatus
from utils.security import get_current_user
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient,AsyncIOMotorGridFSBucket
from database import client,db,collections


fs_bucket = AsyncIOMotorGridFSBucket(db, bucket_name="files")
application_router = APIRouter(prefix="/application", tags=["Applications"])


# ---------------------------------------------------------------------
# CREATE APPLICATION
# Users with any roles can apply
# Prevent duplicate applications for same job
# ---------------------------------------------------------------------


@application_router.post("/applications", response_model=Application)
async def create_application(
    job_rr_id: str = Form(...),
    resume_file: UploadFile = File(...),
    cover_letter_file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    # 1. validate job_rr_id, employee, etc. like you already do
    role = current_user["role"]
    
    # if role not in ["TP", "Non TP"]:
    #     raise HTTPException(
    #         status_code=status.HTTP_403_FORBIDDEN,
    #         detail="Only employees can create applications",
    #     )

    # 2. Validate that job_rr_id exists and job is open (jobs.status is boolean)
    job_rr_id = job_rr_id.strip()

    job = await collections["resource_request"].find_one(
        {
            "resource_request_id": job_rr_id,
            "flag": True,
        }
    )
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with RR ID '{job_rr_id}' not found or is no longer open",
        )

    # 3. Prevent duplicate applications
    employee_id = str(current_user["employee_id"])

    existing = await collections["applications"].find_one(
        {
            "employee_id": employee_id,
            "job_rr_id": job_rr_id,
            "status": {
                "$nin": [
                    ApplicationStatus.WITHDRAWN.value,
                    ApplicationStatus.REJECTED.value,
                ]
            },
        }
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You have already applied for this job",
        )
    
    # 4. Store resume in GridFS (validate extension)
    resume_file_id = None
    if resume_file:
        ext = resume_file.filename.split(".")[-1].lower()
        if ext not in {"pdf", "doc", "docx"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid resume file type. Only .pdf, .doc, .docx are allowed.",
            )
        resume_bytes = await resume_file.read()
        resume_file_id = await fs_bucket.upload_from_stream(
            resume_file.filename,
            resume_bytes,
            metadata={"content_type": resume_file.content_type},
        )

    # 5. Store cover letter in GridFS (validate extension if uploaded)
    cover_letter_file_id = None
    if cover_letter_file:
        ext = cover_letter_file.filename.split(".")[-1].lower()
        if ext not in {"pdf", "doc", "docx"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid cover letter file type. Only .pdf, .doc, .docx are allowed.",
            )
        cl_bytes = await cover_letter_file.read()
        cover_letter_file_id = await fs_bucket.upload_from_stream(
            cover_letter_file.filename,
            cl_bytes,
            metadata={"content_type": cover_letter_file.content_type},
        )

    # 6. Build application doc (just the IDs here)
    application_data = {
        "_id": str(uuid.uuid4()),
        "job_rr_id": job_rr_id,
        "employee_id": str(current_user["employee_id"]),
        "status": ApplicationStatus.DRAFT.value,
        "resume": str(resume_file_id) if resume_file_id else None,   # <- GridFS file id
        "cover_letter": str(cover_letter_file_id) if cover_letter_file_id else None,
        "submitted_at": None,
        "updated_at": datetime.utcnow(),
    }

    result = await collections["applications"].insert_one(application_data)
    created_app = await collections["applications"].find_one({"_id": result.inserted_id})

    return Application(**created_app)



# ---------------------------------------------------------------------
# UPDATE DRAFT APPLICATION
# Only DRAFT status can be modified
# ---------------------------------------------------------------------
@application_router.put("/{app_id}")
async def update_draft(
    app_id: str,
    job_rr_id: str = Form(...),
    resume_file: UploadFile = File(...),
    cover_letter_file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    employee_id = str(current_user["employee_id"])
 
    app = await collections["applications"].find_one({"_id": app_id, "employee_id" : employee_id})
    if not app:
        raise HTTPException(404, "Application not found")
    if app.get("status") != ApplicationStatus.DRAFT.value:
        raise HTTPException(400, "Only draft applications can be edited")
 
    #Validate that job_rr_id exists and job is open
    job_rr_id = job_rr_id.strip()
    job = await collections["resource_request"].find_one(
        {"resource_request_id": job_rr_id, "flag": True}
    )
    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"Job with RR ID '{job_rr_id}' not found or is no longer open",
        )
 
    # Only allow job_rr_id and file updates, not status
    update_fields = {"job_rr_id": job_rr_id}
 
    # Replace resume with new file uploaded
    if resume_file:
        ext = resume_file.filename.split(".")[-1].lower()
        if ext not in {"pdf", "doc", "docx"}:
            raise HTTPException(
                status_code=400,
                detail="Invalid resume file type. Only .pdf, .doc, .docx are allowed.",
            )
        resume_bytes = await resume_file.read()
        resume_file_id = await fs_bucket.upload_from_stream(
            resume_file.filename,
            resume_bytes,
            metadata={"content_type": resume_file.content_type},
        )
        update_fields["resume"] = str(resume_file_id)
        if app.get("resume"):
            try:
                await fs_bucket.delete(ObjectId(app["resume"]))
            except Exception:
                pass
 
    # Replace cover letter with new file uploaded
    if cover_letter_file:
        ext = cover_letter_file.filename.split(".")[-1].lower()
        if ext not in {"pdf", "doc", "docx"}:
            raise HTTPException(
                status_code=400,
                detail="Invalid cover letter file type. Only .pdf, .doc, .docx are allowed.",
            )
        cl_bytes = await cover_letter_file.read()
        cover_letter_file_id = await fs_bucket.upload_from_stream(
            cover_letter_file.filename,
            cl_bytes,
            metadata={"content_type": cover_letter_file.content_type},
        )
        update_fields["cover_letter"] = str(cover_letter_file_id)
        if app.get("cover_letter"):
            try:
                await fs_bucket.delete(ObjectId(app["cover_letter"]))
            except Exception:
                pass
 
    update_fields["updated_at"] = datetime.now(timezone.utc)
 
    await collections["applications"].update_one(
        {"_id": app_id, "employee_id": employee_id},
        {"$set": update_fields},
    )
 
    return {"message": "Your application is Updated"}
 
# ---------------------------------------------------------------------
# SUBMIT APPLICATION
# Move from DRAFT → SUBMITTED
# ---------------------------------------------------------------------
 
@application_router.patch("/{app_id}/submit")
async def update_draft_status(
    app_id: str,
    current_user: dict = Depends(get_current_user),):
   
    employee_id = int(current_user["employee_id"])
    print(employee_id)
 
    # _id is a UUID string, employee_id is int in DB
    app = await collections["applications"].find_one(
        {"_id": app_id}
    )
    print("Found app:", app)
    if not app:
        raise HTTPException(404, "Application not found")
 
    # Only drafts can be submitted
    if app.get("status") != "Draft":
        raise HTTPException(400, "Only draft applications can be edited")
    # Update status
    result = await collections["applications"].update_one(
        {"_id": app_id},
        {
            "$set": {
                "status": ApplicationStatus.SUBMITTED.value,
                "submitted_at": datetime.now(timezone.utc),
            }
        }
    )
    print("Modified count:", result.modified_count)
    return {"message": "Your application is successfully Submitted"}

# ---------------------------------------------------------------------
# WITHDRAW APPLICATION
# Cannot withdraw once shortlisted/interviewed/selected/allocated
# ---------------------------------------------------------------------
 
@application_router.delete("/{app_id}")
async def withdraw(app_id: str, current_user: dict = Depends(get_current_user)):
    print(app_id)
   
    # Find application
    app = await collections["applications"].find_one({"_id": app_id})
   
    # Restrict withdrawal for certain statuses
    if not app or app["status"] in [
        ApplicationStatus.SHORTLISTED, ApplicationStatus.INTERVIEW, ApplicationStatus.SELECTED, ApplicationStatus.ALLOCATED]:
        raise HTTPException(400, "Cannot withdraw")
   
     # Mark as withdrawn
    await collections["applications"].update_one(
        {"_id": app_id},
        {"$set": {"status": ApplicationStatus.WITHDRAWN}}
    )
    return {"message": "Your application is successfully Withdrawn"}

# ---------------------------------------------------------------------
# FILTER APPLICATIONS
# Filter by job_rr_id or status
# ---------------------------------------------------------------------

# Utility function to normalize status values
def normalize_status(value: str | None) -> str | None:
    # If no status is provided, return None
    if value is None:
        return None
    # Strip whitespace and capitalize first letter (e.g. "submitted" -> "Submitted")
    value = value.strip().capitalize()
    try:
        # Try to convert the cleaned string into a valid ApplicationStatus Enum
        return ApplicationStatus(value).value
    except ValueError:
        # If the string is not a valid Enum member, return None
        return None


# GET endpoint to fetch applications with optional filters
@application_router.get("/", response_model=List[Application])
async def get_applications(
    job_rr_id: Optional[str] = Query(None, description="Filter by job requisition ID"),
    status: Optional[str] = Query(None, description="Filter by status"),
    current_user: dict = Depends(get_current_user),
):
    # Step 1: Normalize the status input to match Enum values
    norm_status = normalize_status(status)

    # Step 2: If user provided a status but it's invalid, raise a 400 Bad Request
    if status is not None and norm_status is None:
        raise HTTPException(
            status_code=400,
            detail="Invalid status"
        )

    # Step 3: Build MongoDB query based on provided filters
    if job_rr_id and norm_status:
        # If both job_rr_id and status are provided, filter by both (AND condition)
        query = {"job_rr_id": job_rr_id, "status": norm_status}
    elif job_rr_id:
        # If only job_rr_id is provided, filter by job_rr_id
        query = {"job_rr_id": job_rr_id}
    elif norm_status:
        # If only status is provided, filter by status
        query = {"status": norm_status}
    else:
        # If no filters are provided, return all applications
        query = {}

    # Step 4: Execute query against MongoDB collection
    cursor = collections["applications"].find(query)
    applications = await cursor.to_list(length=100)  # Limit results to 100

    # Step 5: Normalize statuses from DB before returning
    normalized_apps = []
    for app in applications:
        if "status" in app and app["status"]:
            # Clean up the status field to ensure it matches Enum values
            fixed = normalize_status(app["status"])
            if fixed:
                app["status"] = fixed
        # Convert raw MongoDB document into Application Pydantic model
        normalized_apps.append(Application(**app))

    # Step 6: If no applications found, raise 404 Not Found
    if not normalized_apps:
        raise HTTPException(status_code=404, detail="No applications found for given criteria")

    # Step 7: Return the list of normalized Application models
    return normalized_apps
