# ----------------------------- STANDARD LIB IMPORTS -----------------------------
import os

from datetime import datetime

 
# ----------------------------- THIRD-PARTY IMPORTS -----------------------------
import pandas as pd
from io import BytesIO
 
from fastapi import  File, UploadFile, HTTPException,APIRouter,Depends

from apscheduler.triggers.interval import IntervalTrigger

from models import Employee, ResourceRequest, User
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ----------------------------- INTERNAL UTILITIES ------------------------------
from utils.security import get_current_user

from utils.file_upload_utils import log_upload_action,sync_employees_with_db,sync_rr_with_db,read_csv_file,delete_old_files_in_processed,logger,UPLOAD_FOLDER,PROCESSED_FOLDER

from exceptions.file_upload_exceptions import FileFormatException,ValidationException,ReportProcessingException
 
 
# Router for file upload related endpoints
file_upload_router = APIRouter(prefix="/api/upload")
 
@file_upload_router.post("/employees")
async def upload_career_velocity(file: UploadFile = File(...),current_user=Depends(get_current_user)):
    # Only Admin can upload employee data
    if current_user["role"] !="Admin":
        logger.error(f"Unauthorized attempt of logging for employee data upload")
        return HTTPException(status_code=409,detail="Not Authorized")
    
    # Read uploaded file into memory
    content = await file.read()
    
    # Validate file extension
    if not file.filename.lower().endswith((".xlsx", ".xls", ".csv")):
        raise FileFormatException("Only .xlsx, .xls, or .csv files allowed")
 
    # Load file into DataFrame (CSV or Excel)
    try:
        df = (pd.read_csv(BytesIO(content), encoding="utf-8", dtype=str, engine="python", on_bad_lines="skip")
              if file.filename.endswith(".csv") else pd.read_excel(BytesIO(content)))
        # Drop rows that are completely empty
        df = df.dropna(how="all")
    except Exception as e:
        # Wrap any read error in a domain-specific exception
        raise ReportProcessingException(f"Failed to read file: {e}")
 
    # Required columns for employee upload
    required = ["Employee ID", "Employee Name", "Designation", "Band","Primary Technology", "City", "Type"]
    if missing := [c for c in required if c not in df.columns]:
        # If any required column is missing, fail the validation
        raise ValidationException(f"Missing columns: {missing}")
 
    # Lists to track valid employees/users and row-wise errors
    valid_emps, valid_users, errors = [], [], []
    
    # Iterate row-by-row to validate and construct Employee/User objects
    for idx, row in df.iterrows():
        # Clean NaN values and strip whitespace
        row_dict = {k: None if pd.isna(v) else str(v).strip() for k, v in row.to_dict().items()}
        try:
            # Validate using Pydantic model
            emp = Employee(**row_dict)
            # Create corresponding User with role from employee type
            user = User(employee_id=str(emp.employee_id), role=emp.type)
            valid_emps.append(emp)
            valid_users.append(user)
        except Exception as e:
            # Capture validation error with row number (Excel-style index + 2 for header offset)
            errors.append({"row": idx + 2, "error": str(e)})
 
    # Log upload attempt in audit log
    await log_upload_action("employees", file.filename,
                            "CSV" if file.filename.endswith(".csv") else "Excel",
                            current_user["employee_id"], len(df), len(valid_emps), len(errors), errors)
 
    # If no valid employee rows, return early with error sample
    if not valid_emps:
        return {"message": "No valid employees found", "errors_sample": errors[:5]}
 
    # Sync valid employees and users into DB
    result = await sync_employees_with_db(valid_emps, valid_users)
    return {
        "message": "Career Velocity processed successfully",
        "processed": len(valid_emps),
        "failed": len(errors),
        "errors_sample": errors[:5],
        "sync": result
    }
 

@file_upload_router.post("/rr-report")
async def upload_rr_report(file: UploadFile = File(...),current_user=Depends(get_current_user)):
    # Only HM or Admin can upload RR report
    if current_user["role"] not in  ["HM","Admin"]:
        logger.error(f"Unauthorized attempt of logging for rr_report upload")
        return HTTPException(status_code=409,detail="Not Authorized")
    
    # Read entire file into memory
    content = await file.read()
    
    # Validate file extension
    if not file.filename.lower().endswith((".xlsx", ".xls", ".csv")):
        raise FileFormatException("Only Excel/CSV files allowed")
 
    try:
        # ------------------------ CSV HANDLING (Robust Reader) ------------------------
        if file.filename.lower().endswith(".csv"):
            df = read_csv_file(content)
            # Ensure CSV actually has data
            if df is None or df.empty:
                raise ReportProcessingException("CSV file contains no valid rows")

        # ------------------------ EXCEL HANDLING (Pandas) ------------------------
        else:
            # Skip first 6 rows (likely metadata/header noise) and read as strings
            df = pd.read_excel(BytesIO(content), skiprows=6, dtype=str)
            # Drop fully empty rows
            df = df.dropna(how="all")
    except Exception as e:
        # Wrap any processing/read error
        raise ReportProcessingException(f"Failed to read RR report: {e}")
 
    # Ensure key column for RR exists
    if "Resource Request ID" not in df.columns:
        raise ValidationException("Column 'Resource Request ID' is required")
 
    # Lists to collect valid RRs and errors
    valid_rrs, errors = [], []
    
    # Process each row from the RR report
    for idx, row in df.iterrows():
        rr_id = row.get("Resource Request ID")
        # Skip rows without RR ID
        if not rr_id or pd.isna(rr_id):
            continue
        # Clean NaN but preserve actual values
        row_dict = {k: None if pd.isna(v) else v for k, v in row.to_dict().items()}
        # Newly uploaded entries considered active
        row_dict["rr_status"] = True
        try:
            # Validate and construct ResourceRequest model
            valid_rrs.append(ResourceRequest(**row_dict))
        except Exception as e:
            # Row index offset +8 assuming original Excel header structure
            errors.append({"row": idx + 8, "rr_id": str(rr_id), "error": str(e)})
 
    # Audit log entry for RR upload
    await log_upload_action("rr_report", file.filename,
                            "CSV" if file.filename.endswith(".csv") else "Excel",
                            current_user["employee_id"], len(df), len(valid_rrs), len(errors), errors)
 
    # If no valid RRs, return early with errors
    if not valid_rrs:
        return {"message": "No valid RRs found", "errors_sample": errors[:5]}
 
    # Sync RR data with DB (insert/reactivate/deactivate logic handled inside)
    await sync_rr_with_db(valid_rrs)
    return {
        "message": "RR Report processed successfully",
        "valid_requests": len(valid_rrs),
        "failed": len(errors),
        "errors_sample": errors[:5]
    }


# ----------------------------- BACKGROUND RR PROCESSOR -----------------------------
async def process_updated_rr_report():
    # List all files present in unprocessed upload folder
    files = [f for f in os.listdir(UPLOAD_FOLDER)
             if f.lower().endswith((".xlsx", ".xls", ".csv"))]
    
    # If no unprocessed files, nothing to do
    if not files:
        return
 
    # Pick the "latest" based on lexical sort (typically last modified name pattern)
    latest = sorted(files)[-1]
    src = os.path.join(UPLOAD_FOLDER, latest)
    # Build destination path in processed folder with timestamp prefix
    dst = os.path.join(PROCESSED_FOLDER, f"{datetime.now():%Y%m%d_%H%M%S}_{latest}")
 
    try:
        # Open the file in binary mode for re-wrapping as UploadFile
        with open(src, "rb") as f:
            fake_file = UploadFile(filename=latest, file=BytesIO(f.read()))
        # Call the same upload_rr_report API internally with a system HM user
        await upload_rr_report(fake_file,{"role":"HM","employee_id":"system"})
        # Move the successfully processed file to processed folder
        os.rename(src, dst)
        logger.info(f"Auto-processed RR: {latest} → processed/")
    except Exception as e:
        # Log any failure while auto-processing
        logger.error(f"Auto RR failed for {latest}: {e}")


# ----------------------------- APSCHEDULER SETUP -----------------------------
# Create AsyncIO-based scheduler instance
scheduler = AsyncIOScheduler()
# Job 1: periodically process unprocessed RR files every 24 hours
scheduler.add_job(process_updated_rr_report, IntervalTrigger(hours=24), id="process_updated_files")
# Job 2: periodically clean old processed files every 1 day
scheduler.add_job(delete_old_files_in_processed,  IntervalTrigger(days=1) , id="delete_old_files")
# Start the scheduler to enable background jobs
scheduler.start()
