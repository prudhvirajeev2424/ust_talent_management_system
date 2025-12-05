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
 
 