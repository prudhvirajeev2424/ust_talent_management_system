# --------------------------- IMPORTS ---------------------------
from datetime import datetime, timezone,timedelta
from typing import List
import chardet
from database import collections
from models import Employee, ResourceRequest , User
from io import StringIO
import pandas as pd
import csv
import os
import logging
 

# --------------------------- LOGGER SETUP ---------------------------
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[
                        logging.FileHandler("app.log", encoding='utf-8'),
                    ])
logger = logging.getLogger("RRProcessor")

# --------------------------- FOLDER PATHS ---------------------------
UPLOAD_FOLDER = "upload_files/unprocessed"
PROCESSED_FOLDER = "upload_files/processed"


# --------------------------- AUDIT LOGGING ---------------------------
async def log_upload_action(audit_type: str, filename: str, file_type: str,
                           uploaded_by: str, total_rows: int, valid_rows: int,
                           failed_rows: int, sample_errors):
    # Insert audit details into database
    await collections["audit_logs"].insert_one({
        "audit_type": audit_type,
        "filename": filename,
        "file_type": file_type,
        "uploaded_by": uploaded_by or "System",
        "upload_time_utc": datetime.now(timezone.utc),
        "total_rows": total_rows,
        "valid_rows": valid_rows,
        "failed_rows": failed_rows,
        "sample_errors": sample_errors,
    })
 
 
# --------------------------- DATE NORMALIZATION ---------------------------
def convert_dates_for_mongo(data: dict):
    """Convert date objects to UTC datetime for MongoDB storage."""
    from datetime import date, time
    # Loop through dict and convert date objects
    for k, v in data.items():
        if isinstance(v, dict):
            data[k] = convert_dates_for_mongo(v)
        elif isinstance(v, date) and not isinstance(v, datetime):
            data[k] = datetime.combine(v, time.min).replace(tzinfo=timezone.utc)
    return data
 
 
# --------------------------- RR DATABASE SYNC ---------------------------
async def sync_rr_with_db(validated_rrs: List[ResourceRequest]):
    # IDs present in uploaded file
    uploaded_ids = {rr.resource_request_id for rr in validated_rrs}
 
    # Fetch existing RRs from DB
    existing_rrs = await collections["resource_request"].find(
        {}, {"resource_request_id": 1, "rr_status": 1}
    ).to_list(None)
    rr_map = {r["resource_request_id"]: r for r in existing_rrs}
 
    rr_insert, rr_reactivate = [], []
    
    # Process uploaded RRs
    for rr in validated_rrs:
        rr_id = rr.resource_request_id
        rr_data = convert_dates_for_mongo(rr.model_dump(by_alias=False))
 
        if rr_id not in rr_map:
            rr_insert.append(rr_data)
        elif not rr_map[rr_id].get("rr_status"):
            rr_reactivate.append({"filter": {"resource_request_id": rr_id},
                                  "update": {"$set": {"rr_status": True}}})
 
    # Deactivate RRs missing in upload
    deactivate_rr = [{"filter": {"resource_request_id": rid}, "update": {"$set": {"rr_status": False}}}
                     for rid in rr_map if rid not in uploaded_ids and rr_map[rid].get("rr_status")]
    
    # Execute DB operations
    if rr_insert:
        await collections["resource_request"].insert_many(rr_insert, ordered=False)

    for op in rr_reactivate + deactivate_rr:
        await collections["resource_request"].update_one(op["filter"], op["update"])
    
    return {
        "rr_inserted": len(rr_insert),
        "rr_reactivated+deactivated": len(rr_reactivate) + len(deactivate_rr),
    }
 
 
# --------------------------- DELETE OLD FILES ---------------------------
async def delete_old_files_in_processed():
    now = datetime.now()
    # Loop through processed folder
    for filename in os.listdir(PROCESSED_FOLDER):
        file_path = os.path.join(PROCESSED_FOLDER, filename)
        
        if os.path.isfile(file_path):
            file_creation_time = datetime.fromtimestamp(os.path.getctime(file_path))
            
            # Delete if older than 7 days
            if now - file_creation_time > timedelta(weeks=1):
                try:
                    os.remove(file_path)
                    logger.info(f"Deleted old file: {filename}")
                except Exception as e:
                    logger.error(f"Failed to delete {filename}: {e}")
 
 
# --------------------------- EMPLOYEE + USER SYNC ---------------------------
async def sync_employees_with_db(employees: List[Employee], users: List[User]):
 
    # Fetch existing employees
    existing = await collections["employees"].find({}, {"employee_id": 1, "status": 1}).to_list(None)
    emp_map = {e["employee_id"]: e for e in existing}
 
    # Fetch existing users
    existing_users = await collections["users"].find({}, {"employee_id": 1}).to_list(None)
    user_set = {u["employee_id"] for u in existing_users}
 
    inserts_emp, inserts_user, updates = [], [], []
 
    # Loop through uploaded employees
    for emp, user in zip(employees, users):
        eid = emp.employee_id
        emp_data = convert_dates_for_mongo(emp.model_dump(by_alias=False))
        user_data = user.model_dump(by_alias=False)
 
        # Insert new employee
        if eid not in emp_map:
            emp_data["status"] = True
            inserts_emp.append(emp_data)
            inserts_user.append(user_data)
        else:
            # Reactivate if inactive
            if not emp_map[eid].get("status"):
                updates.append({"filter": {"employee_id": eid}, "update": {"$set": {"status": True}}})
            
            # Update employee data
            updates.append({"filter": {"employee_id": eid}, "update": {"$set": emp_data}})
            
            # Insert user if missing
            if str(eid) not in user_set:
                inserts_user.append(user_data)
 
    # Insert all new employees
    if inserts_emp:
        await collections["employees"].insert_many(inserts_emp, ordered=False)

    # Insert all new users
    if inserts_user:
        await collections["users"].insert_many(inserts_user, ordered=False)

    # Update existing employees
    for op in updates:
        await collections["employees"].update_one(op["filter"], op["update"])
 
    return {
        "employees_inserted": len(inserts_emp),
        "employees_updated": len(updates),
        "users_inserted": len(inserts_user),
    }
    

# --------------------------- CSV READER ---------------------------
def read_csv_file(content: bytes):
    """Read CSV reliably even if corrupted or irregular."""
    
    # Auto-detect encoding
    enc = chardet.detect(content).get("encoding") or "utf-8"

    # Decode bytes → text
    text = content.decode(enc, errors="ignore")
    stream = StringIO(text)

    # Create CSV reader
    reader = csv.reader(stream)

    # Remove empty rows
    rows = [row for row in reader if any(cell.strip() for cell in row)]

    # If file empty return None
    if not rows:
        return None

    # Header = first row
    header = rows[0]
    data_rows = rows[1:]

    # Normalize row length
    data = [row + [""] * (len(header) - len(row)) for row in data_rows]

    # Build DataFrame
    df = pd.DataFrame(data, columns=header)
    return df
