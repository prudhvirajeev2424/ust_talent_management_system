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
 

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[
                        logging.FileHandler("app.log", encoding='utf-8'),  # Log to a file
                        # logging.StreamHandler()  # Optionally, still log to terminal
                    ])
logger = logging.getLogger("RRProcessor")

UPLOAD_FOLDER = "upload_files/unprocessed"
PROCESSED_FOLDER = "upload_files/processed"

async def log_upload_action(audit_type: str, filename: str, file_type: str,
                           uploaded_by: str, total_rows: int, valid_rows: int,
                           failed_rows: int, sample_errors):
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
 
 
def convert_dates_for_mongo(data: dict):
    """Convert date objects to UTC datetime for MongoDB storage."""
    from datetime import date, time
    for k, v in data.items():
        if isinstance(v, dict):
            data[k] = convert_dates_for_mongo(v)
        elif isinstance(v, date) and not isinstance(v, datetime):
            data[k] = datetime.combine(v, time.min).replace(tzinfo=timezone.utc)
    return data
 
async def sync_rr_with_db(validated_rrs: List[ResourceRequest]):
    uploaded_ids = {rr.resource_request_id for rr in validated_rrs}
 
    # Fetch current state
    existing_rrs = await collections["resource_request"].find(
        {}, {"Resource Request ID": 1, "rr_status": 1}
    ).to_list(None)
    rr_map = {r["Resource Request ID"]: r for r in existing_rrs}
 
    rr_insert, rr_reactivate = [], []
    for rr in validated_rrs:
        rr_id = rr.resource_request_id
        rr_data = convert_dates_for_mongo(rr.model_dump(by_alias=False))
 
        if rr_id not in rr_map:
            rr_insert.append(rr_data)
        elif not rr_map[rr_id].get("rr_status"):
            rr_reactivate.append({"filter": {"Resource Request ID": rr_id},
                                  "update": {"$set": {"rr_status": True}}})
 
   
    # Deactivate removed RRs
    deactivate_rr = [{"filter": {"Resource Request ID": rid}, "update": {"$set": {"rr_status": False}}}
                     for rid in rr_map if rid not in uploaded_ids and rr_map[rid].get("rr_status")]
    # Bulk operations
    if rr_insert:   await collections["resource_request"].insert_many(rr_insert, ordered=False)
    for op in rr_reactivate + deactivate_rr:
        await collections["resource_request"].update_one(op["filter"], op["update"])
    return {
        "rr_inserted": len(rr_insert),
        "rr_reactivated+deactivated": len(rr_reactivate) + len(deactivate_rr),
    }
 
async def delete_old_files_in_processed():
    now = datetime.now()
    for filename in os.listdir(PROCESSED_FOLDER):
        file_path = os.path.join(PROCESSED_FOLDER, filename)
        if os.path.isfile(file_path):
            file_creation_time = datetime.fromtimestamp(os.path.getctime(file_path))
            if now - file_creation_time > timedelta(weeks=1):  # Older than 7 days
                try:
                    os.remove(file_path)
                    logger.info(f"Deleted old file: {filename}")
                except Exception as e:
                    logger.error(f"Failed to delete {filename}: {e}")
 
async def sync_employees_with_db(employees: List[Employee], users: List[User]):
 
    existing = await collections["employees"].find({}, {"employee_id": 1, "status": 1}).to_list(None)
    emp_map = {e["employee_id"]: e for e in existing}
 
    existing_users = await collections["users"].find({}, {"employee_id": 1}).to_list(None)
    user_set = {u["employee_id"] for u in existing_users}
 
    inserts_emp, inserts_user, updates = [], [], []
 
    for emp, user in zip(employees, users):
        eid = emp.employee_id
        emp_data = convert_dates_for_mongo(emp.model_dump(by_alias=False))
        user_data = user.model_dump(by_alias=False)
 
        if eid not in emp_map:
            emp_data["status"] = True
            inserts_emp.append(emp_data)
            inserts_user.append(user_data)
        else:
            if not emp_map[eid].get("status"):
                updates.append({"filter": {"employee_id": eid}, "update": {"$set": {"status": True}}})
            updates.append({"filter": {"employee_id": eid}, "update": {"$set": emp_data}})
            if str(eid) not in user_set:
                inserts_user.append(user_data)
 
    if inserts_emp:  await collections["employees"].insert_many(inserts_emp, ordered=False)
    if inserts_user: await collections["users"].insert_many(inserts_user, ordered=False)
    for op in updates:
        await collections["employees"].update_one(op["filter"], op["update"])
 
    return {
        "employees_inserted": len(inserts_emp),
        "employees_updated": len(updates),
        "users_inserted": len(inserts_user),
    }
    
def read_csv_file(content: bytes):
    """Read CSV reliably even if corrupted or irregular."""
    # Detect encoding
    enc = chardet.detect(content).get("encoding") or "utf-8"

    text = content.decode(enc, errors="ignore")
    stream = StringIO(text)


    reader = csv.reader(stream)

    # Remove completely empty rows
    rows = [row for row in reader if any(cell.strip() for cell in row)]

    if not rows:
        return None  # No data

    # Convert to DataFrame-like object
    header = rows[0]
    data_rows = rows[1:]

    # Normalize row lengths
    data = [row + [""] * (len(header) - len(row)) for row in data_rows]

    df = pd.DataFrame(data, columns=header)
    return df
