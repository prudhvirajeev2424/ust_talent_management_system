from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import os

load_dotenv()


client = AsyncIOMotorClient(os.getenv("MONGODB_CLIENT"))
db = client.talent_management

collections = {
    "employees": db.employees,
    "applications": db.applications,
    "users": db.users,
    "refresh_tokens": db.refresh_tokens,
    "audit_logs": db.audit_logs,
    "block_list_tokens":db.block_list_tokens,
    "resource_request":db.resource_request,
    "admin_logs":db["admin_logs"]
    
}