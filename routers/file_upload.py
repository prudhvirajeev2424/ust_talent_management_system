import os

from datetime import datetime

 
import pandas as pd
from io import BytesIO
 
from fastapi import  File, UploadFile, HTTPException,APIRouter,Depends

from apscheduler.triggers.interval import IntervalTrigger

from models import Employee, ResourceRequest, User
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from utils.security import get_current_user

from utils.file_upload_utils import log_upload_action,sync_employees_with_db,sync_rr_with_db,read_csv_file,delete_old_files_in_processed,logger,UPLOAD_FOLDER,PROCESSED_FOLDER

from exceptions.file_upload_exceptions import FileFormatException,ValidationException,ReportProcessingException
 
 
file_upload_router = APIRouter(prefix="/api/upload")
 
@file_upload_router.post("/employees")
async def upload_career_velocity(file: UploadFile = File(...),current_user=Depends(get_current_user)):
    if current_user["role"] !="Admin":
        logger.error(f"Unauthorized attempt of logging for employee data upload")
        return HTTPException(status_code=409,detail="Not Authorized")
    content = await file.read()
    if not file.filename.lower().endswith((".xlsx", ".xls", ".csv")):
        raise FileFormatException("Only .xlsx, .xls, or .csv files allowed")
 
    # Load file
    try:
        df = (pd.read_csv(BytesIO(content), encoding="utf-8", dtype=str, engine="python", on_bad_lines="skip")
              if file.filename.endswith(".csv") else pd.read_excel(BytesIO(content)))
        df = df.dropna(how="all")
    except Exception as e:
        raise ReportProcessingException(f"Failed to read file: {e}")
 
    required = ["Employee ID", "Employee Name", "Designation", "Band", "City", "Type"]
    if missing := [c for c in required if c not in df.columns]:
        raise ValidationException(f"Missing columns: {missing}")
 
    valid_emps, valid_users, errors = [], [], []
    for idx, row in df.iterrows():
        row_dict = {k: None if pd.isna(v) else str(v).strip() for k, v in row.to_dict().items()}
        try:
            emp = Employee(**row_dict)
            user = User(employee_id=str(emp.employee_id), role=emp.type)
            valid_emps.append(emp)
            valid_users.append(user)
        except Exception as e:
            errors.append({"row": idx + 2, "error": str(e)})
 
    await log_upload_action("employees", file.filename,
                            "CSV" if file.filename.endswith(".csv") else "Excel",
                            current_user["employee_id"], len(df), len(valid_emps), len(errors), errors[:5])
 
    if not valid_emps:
        return {"message": "No valid employees found", "errors_sample": errors[:5]}
 
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
    if current_user["role"] not in  ["HM","Admin"]:
        logger.error(f"Unauthorized attempt of logging for rr_report upload")
        return HTTPException(status_code=409,detail="Not Authorized")
    content = await file.read()
    if not file.filename.lower().endswith((".xlsx", ".xls", ".csv")):
        raise FileFormatException("Only Excel/CSV files allowed")
 
    try:
        if file.filename.lower().endswith(".csv"):
            df = read_csv_file(content)

            if df is None or df.empty:
                raise ReportProcessingException("CSV file contains no valid rows")

        # ------------------------ EXCEL HANDLING (Pandas) ------------------------
        else:
            df = pd.read_excel(BytesIO(content), skiprows=6, dtype=str)
            df = df.dropna(how="all")
    except Exception as e:
        raise ReportProcessingException(f"Failed to read RR report: {e}")
 
    if "Resource Request ID" not in df.columns:
        raise ValidationException("Column 'Resource Request ID' is required")
 
    valid_rrs, errors = [], []
    for idx, row in df.iterrows():
        rr_id = row.get("Resource Request ID")
        if not rr_id or pd.isna(rr_id):
            continue
        row_dict = {k: None if pd.isna(v) else v for k, v in row.to_dict().items()}
        row_dict["rr_status"] = True
        try:
            valid_rrs.append(ResourceRequest(**row_dict))
        except Exception as e:
            errors.append({"row": idx + 8, "rr_id": str(rr_id), "error": str(e)})
 
    await log_upload_action("rr_report", file.filename,
                            "CSV" if file.filename.endswith(".csv") else "Excel",
                            current_user["employee_id"], len(df), len(valid_rrs), len(errors), errors[:5])
 
    if not valid_rrs:
        return {"message": "No valid RRs found", "errors_sample": errors[:5]}
 
    await sync_rr_with_db(valid_rrs)
    return {
        "message": "RR Report processed successfully",
        "valid_requests": len(valid_rrs),
        "failed": len(errors),
        "errors_sample": errors[:5]
    }


async def process_updated_rr_report():
    files = [f for f in os.listdir(UPLOAD_FOLDER)
             if f.lower().endswith((".xlsx", ".xls", ".csv"))]
    if not files:
        return
 
    latest = sorted(files)[-1]
    src = os.path.join(UPLOAD_FOLDER, latest)
    dst = os.path.join(PROCESSED_FOLDER, f"{datetime.now():%Y%m%d_%H%M%S}_{latest}")
 
    try:
        with open(src, "rb") as f:
            fake_file = UploadFile(filename=latest, file=BytesIO(f.read()))
        await upload_rr_report(fake_file,{"role":"HM","employee_id":"system"})
        os.rename(src, dst)
        logger.info(f"Auto-processed RR: {latest} → processed/")
    except Exception as e:
        logger.error(f"Auto RR failed for {latest}: {e}")

scheduler = AsyncIOScheduler()
scheduler.add_job(process_updated_rr_report, IntervalTrigger(hours=24), id="process_updated_files")
scheduler.add_job(delete_old_files_in_processed,  IntervalTrigger(days=1) , id="delete_old_files")
scheduler.start()
 