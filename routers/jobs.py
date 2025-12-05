from fastapi import APIRouter, Depends, HTTPException
from typing import Optional, List, Union, Any
from fastapi import Body
from models import ResourceRequest
from utils import jobs_crud
from utils.security import get_current_user


# Create a router with the prefix /jobs
jobs_router = APIRouter(prefix="/jobs")


# Endpoint to get all jobs with optional location filter
# Accessible by any authenticated user
@jobs_router.get("/", response_model=List[dict])
async def get_all_jobs(location: Optional[str] = None, current_user=Depends(get_current_user)):
    # Delegates job fetching logic to jobs_crud
    return await jobs_crud.get_jobs(location, current_user)

@jobs_router.get("/managers",response_model=List[dict])
async def get_jobs_under_manager(current_user=Depends(get_current_user)):
    print(current_user["role"])
    if current_user["role"] == "HM" or current_user["role"] == "WFM":
        return await jobs_crud.jobs_under_manager(current_user)
    else:
        raise HTTPException(status_code=403, detail="Not Authorized")
    


# Endpoint to create a new job
# Only HM (Hiring Manager) is authorized
@jobs_router.post("/create")
async def create_new_job(new_job: ResourceRequest, current_user=Depends(get_current_user)):
    # Check role-based access
    if current_user["role"] != "HM":
        raise HTTPException(status_code=403, detail="Not Authorized")
    try:
        # Call CRUD function to create resource request
        await jobs_crud.create_resource_request(new_job, current_user)
        return {"detail": "Job Created Successfully"}
    except Exception as e:
        # Handle errors during creation
        raise HTTPException(status_code=400, detail=f"Error: {e}")


# Endpoint to update an existing job
# Only HM is allowed to modify
@jobs_router.put("/modify")
async def update_job(request_id: str, updated_job: ResourceRequest, current_user=Depends(get_current_user)):
    # Check if user is HM
    if current_user["role"] != "HM":
        raise HTTPException(status_code=403, detail="Not Authorized")
    try:
        # Update both job and resource request based on ID
        await jobs_crud.update_resource_request(request_id, updated_job, current_user)
        return {"detail": "Job Updated Successfully"}
    except Exception as e:
        # Handle errors during update
        raise HTTPException(status_code=400, detail=f"Error: {e}")


# Endpoint to get skills availability for HM
# Only HM (Hiring Manager) is authorized
# Returns all required skills from their resource requests and the count of employees skilled in each
# Optional filters: resource_request_id (filter by specific request) and skill (filter by specific skill)
@jobs_router.get("/skills/availability")
async def get_skills_availability(
    current_user=Depends(get_current_user),
    resource_request_id: Optional[str] = None,
    skill: Optional[str] = None
):
    # Check if user is HM
    if current_user["role"] != "HM":
        raise HTTPException(status_code=403, detail="Not Authorized")
    try:
        # Call CRUD function to get skills availability with optional filters
        skills_data = await jobs_crud.get_skills_availability(current_user, resource_request_id, skill)
        return skills_data
    except Exception as e:
        # Handle errors
        raise HTTPException(status_code=400, detail=f"Error: {e}")


# Endpoint to patch a single field on a ResourceRequest (HM only)
@jobs_router.patch("/patch")
async def patch_resource_request(
    request_id: str,
    key: str,
    value: Any = Body(...),
    current_user=Depends(get_current_user),
):
    # Check if the current user has the role of "HM" (Hiring Manager)
    if current_user["role"] != "HM":
        # If the user is not an "HM", raise an HTTPException with a 403 status code (Forbidden)
        raise HTTPException(status_code=403, detail="Not Authorized")

    try:
        # Call the CRUD function to patch a specific field in the resource request
        result = await jobs_crud.patch_resource_request_single(request_id, key, value, current_user)
        # If the patch is successful (result is True), return a success message
        if result:
            return {"detail": "ResourceRequest patched successfully"}
        else:
            # If no document is updated, raise an HTTPException with a 400 status code (Bad Request)
            raise HTTPException(status_code=400, detail="No document updated")
    except PermissionError as e:
        # If a PermissionError is raised during the operation, return a 403 Forbidden HTTPException
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        # Catch any other exceptions and return a 400 Bad Request HTTPException with the error message
        raise HTTPException(status_code=400, detail=f"Error: {e}")
    
    
@jobs_router.delete("/delete")
async def delete_resource_request(
    # The unique ID of the resource request to be deleted
    request_id: str,
    current_user=Depends(get_current_user)
):
    # Check if the current user has the role of "HM" (Hiring Manager)
    if current_user["role"] != "HM":
        # If the user is not an "HM", raise an HTTPException with a 403 status code (Forbidden)
        raise HTTPException(status_code=403, detail="Not Authorized")
 
    try:
         # Call the CRUD function to delete the resource request by its ID
        result = await jobs_crud.delete_resource_request(request_id, current_user)
        if result:
            return {"detail": "ResourceRequest Deleted successfully"}
        else:
            # If the deletion is successful (result is True), return a success message
            raise HTTPException(status_code=400, detail="No document Found")
        # If a PermissionError is raised during the operation, return a 403 Forbidden HTTPException
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        # Catch any other exceptions and return a 400 Bad Request HTTPException with the error message
        raise HTTPException(status_code=400, detail=f"Error: {e}")