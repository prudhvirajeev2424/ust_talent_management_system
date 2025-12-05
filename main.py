from fastapi import FastAPI,Depends
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from routers.jobs import jobs_router
from routers.file_upload import file_upload_router
from routers.application import application_router

import os
load_dotenv()

from routers import auth
from utils.security import get_current_user
from routers import manager_workflow
# , file_upload, job, employee, application, manager_workflow, admin

app = FastAPI(title="Talent Management System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MongoDB Connection
client = AsyncIOMotorClient(os.getenv("MONGODB_CLIENT"))
db = client.talent_management

# app.include_router(auth.router, tags=["Auth"])
# # ager_workflow.router, prefix="/api/manager", tags=["Manager Workflow"])

# @app.get("/" )
# def root():
#     return {"message": "Talent Management System API"}
app.include_router(auth.router, tags=["Auth"])
app.include_router(jobs_router, tags=["Jobs"])
app.include_router(application_router, tags=["Applications"])
app.include_router(manager_workflow.manager_router,tags=["Manager Workflow"])
app.include_router(file_upload_router, tags=["File Upload"])

# Protected root endpoint
@app.get("/")
async def root(current_user=Depends(get_current_user)):
    """
    Root endpoint that requires authentication.
    """
    return {"message": f"Hello, {current_user['employee_id']}! Welcome to the Talent Management System API."}
# app.include_router(admin.router, tags=["Admin"])

# app.include_router(job.router, prefix="/api/jobs", tags=["Jobs"])
# app.include_router(employee.router, prefix="/api/employees", tags=["Employees"])
# app.include_router(application.router, prefix="/api/applications", tags=["Applications"])
# app.include_router(man