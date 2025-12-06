from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import os
import pymongo
import gridfs

load_dotenv()


client = AsyncIOMotorClient(os.getenv("MONGODB_CLIENT"))
db = client.talent_management
sync_client = pymongo.MongoClient(os.getenv("MONGODB_CLIENT"))
sync_db = sync_client.talent_management


# Use synchronous GridFS with pymongo
fs = gridfs.GridFS(sync_db,collection="files")


collections = {
    "employees": db.employees,
    "applications": db.applications,
    "users": db.users,
    "refresh_tokens": db.refresh_tokens,
    "audit_logs": db.audit_logs,
    "block_list_tokens":db.block_list_tokens,
    "resource_request":db.resource_request,
    "login_attempts":db["login_attempts"],
    "admin_logs":db["admin_logs"],
    "files":db.files.files,
    "reset_collection":db.reset_tokens
    
}


def get_gridfs():
    return fs
 
applications = db.applications
resource_request= db.resource_request
employees = db.employees
files=db.files.files
