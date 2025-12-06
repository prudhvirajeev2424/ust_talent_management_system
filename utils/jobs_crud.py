from typing import Optional,Dict,Any
from motor.motor_asyncio import AsyncIOMotorClient
from models import ResourceRequest
import csv
import os
from datetime import datetime,date
from utils.file_upload_utils import logger

# Define the path for the CSV file
CSV_PATH = os.path.join(os.path.dirname(__file__), "../upload_files/unprocessed/updated_jobs.csv")

# Create MongoDB async client connection 
client = AsyncIOMotorClient(os.getenv("MONGODB_CLIENT"))
db = client.talent_management

# List of job grade bands for comparison
BANDS = ['A1','A2','A3','B1','B2','B3','C1','C2','C3','D1','D2','D3']

#Map resource_request doc to job-like response
async def map_job(doc):
        
        return {
            "rr_id": doc.get("resource_request_id"),
            "title": doc.get("project_name"),
            "city": doc.get("city"),
            "state": doc.get("state"),
            "country": doc.get("country"),
            "required_skills": (doc.get("mandatory_skills") or []) + (doc.get("optional_skills") or []),
            "description": doc.get("job_description") or doc.get("ust_role_description"),
            "rr_start_date": doc.get("rr_start_date"),
            "rr_end_date": doc.get("rr_end_date"),
            "job_grade": doc.get("job_grade"),
            "account_name": doc.get("account_name"),
            "project_id": doc.get("project_id")
        }


# Role-based job access:
#     - Admin: all jobs
#     - Employee (TP): jobs in band ±1, matching skills, optional location
#     - Employee (non-TP): all jobs
#     - WFM: jobs where wfm_id != jobs wfm_id
#     - HM: jobs where hm_id != jobs hm_id
 
async def get_jobs(location: Optional[str], current_user):
    try:
    
        role = current_user["role"] # Get the role of the current user (Admin, Employee, WFM, HM)
    
        # Admin has access to all jobs
        if role == "Admin" or role=="TP Manager":
            
            # Fetch the jobs as a list 
            query={}
            if location:
                query["city"] = location
            cursor = db.resource_request.find(query)
            docs = await cursor.to_list(length=100)
            for d in docs:
                d["_id"] = str(d["_id"])
            logger.info(f"Fetched jobs for Role: {role}")
            return [await map_job(d) for d in docs]

        # Employee role-based access
        elif role in ["TP", "Non TP"]:
        
            emp = await db.employees.find_one({"employee_id": int(current_user['employee_id'])})
            #Role - TP
            if emp and role == "TP":
                curr_band = emp["band"]
                curr_skills = emp.get("detailed_skills", [])

                # Find the index of the current band
                indx = BANDS.index(curr_band)
                above_band = BANDS[indx+1] if indx < len(BANDS)-1 else BANDS[indx]
                below_band = BANDS[indx-1] if indx > 0 else BANDS[indx]
    
                query = {
                    "job_grade": {"$in": [curr_band, above_band, below_band]},  # Filter jobs based on bands ±1
                    "mandatory_skills": {"$in": curr_skills},  # Filter jobs based on required skills
                    "flag":True,
                }
                # Optional filter by location (city)
                if location:
                    query["city"] = location
    
                # Execute the query to find jobs
                cursor = db.resource_request.find(query)
                docs = await cursor.to_list(length=100)
                for d in docs:
                    d["_id"] = str(d["_id"])
                logger.info(f"Fetched jobs for TP Employee: {current_user['employee_id']}")
                return [await map_job(d) for d in docs]
            
            else:
                #Role - Non TP
                query = {}
                if location:
                    query["city"] = location
                query["flag"]=True
                cursor = db.resource_request.find(query)
                docs = await cursor.to_list(length=100)
                for d in docs:
                    d["_id"] = str(d["_id"])
                logger.info(f"Fetched jobs for Non TP Employee : {current_user['employee_id']}")
                return [await map_job(d) for d in docs]

        # WFM role can access jobs based on WFM ID
        elif role == "WFM":
            query = {"wfm_id": {"$ne":current_user['employee_id']}}
            
            if location:
                query["city"] = location
                
            cursor = db.resource_request.find(query)
            
            docs = await cursor.to_list(length=100)
            
            for d in docs:
                d["_id"] = str(d["_id"])
                
            logger.info(f"Fetched jobs for WFM Employee:{current_user['employee_id']}")
            
            return [await map_job(d) for d in docs]

        # HM role can access jobs based on HM ID
        elif role == "HM":
            query = {"hm_id": {"$ne":current_user["employee_id"]}}
            
            if location:
                query["city"] = location
                
            cursor = db.resource_request.find(query)
            
            docs = await cursor.to_list(length=100)
            
            for d in docs:
                d["_id"] = str(d["_id"])
                
            logger.info(f"Fetched jobs for HM Employee :{current_user['employee_id']}")
            
            return [await map_job(d) for d in docs]
        
    except Exception as e:
        logger.error(f"Error in get_jobs for employee_id={current_user.get('employee_id')}, role={current_user.get('role')}: {str(e)}")
        return {"details":f"Error:{e}"}

# Access to the jobs for managers 
#     - WFM: jobs where wfm_id == current_user.id
#     - HM : jobs where hm_id== current_user 
async def jobs_under_manager(current_user):
    
    role= current_user["role"]
    
    # WFM role can access jobs based on WFM ID
    if role == "WFM":
        
        query = {"wfm_id": current_user["employee_id"]}
        
        cursor = db.resource_request.find(query)
        
        docs = await cursor.to_list(length=100)
        
        for d in docs:
            d["_id"] = str(d["_id"])
            
        logger.info(f"Accessing jobs under wfm_id: {current_user['employee_id']}")
        return docs
 
     # HM role can access jobs based on HM ID
    elif role == "HM":
        
        query = {"hm_id": current_user["employee_id"]}
        
        cursor = db.resource_request.find(query)
        
        docs = await cursor.to_list(length=100)
        
        for d in docs:
            d["_id"] = str(d["_id"])
            
        logger.info(f"Accessing jobs under hm_id: {current_user['employee_id']}")
        return docs
    
    
# Function to create a job and associated resource request, and write to a CSV file
async def create_resource_request(job_data: ResourceRequest, current_user):
    try:
        row = job_data.dict(by_alias=False) # Convert the ResourceRequest data to a dictionary using aliases
        
        if row.get('hm_id') != current_user['employee_id']:
            logger.warning(f"Unauthorized job creation attempt by hm_id={current_user['employee_id']}")
            raise PermissionError("You do not have permission to create jobs for other HMs.")

        # Check if file exists to decide whether to write header
        file_exists = os.path.isfile(CSV_PATH)

        # Open the CSV file in append mode
        with open(CSV_PATH, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=row.keys())
            if not file_exists:
                writer.writeheader()
                logger.info(f"CSV header written to {CSV_PATH}")
                
            writer.writerow(row)
            logger.info(f"job created and appending it into csv file path: {CSV_PATH}")
            
    except Exception as e:
        logger.error(f"Error creating resource request for employee_id={current_user.get('employee_id')}: {str(e)}")
        raise Exception(f"{e}")



# convert datetime.date to datetime.datetime 
def normalize_dates(doc: dict) -> dict:
    # Convert all datetime.date values to datetime.datetime
    for key, value in doc.items():
        if isinstance(value, date) and not isinstance(value, datetime):
            # Convert date → datetime at midnight UTC
            doc[key] = datetime(value.year, value.month, value.day) # If value is a date object but not datetime
    return doc

# Function to update both the ResourceRequest documents
# - Only HMs can update.
# - HM can only update jobs they own (hm_id == current_user["employee_id"]). 

async def update_resource_request(request_id: str, update_data: ResourceRequest, current_user):
   
    if current_user["role"] != "HM":
        logger.warning(f"Unauthorized update attempt by role={current_user['role']}, employee_id={current_user['employee_id']}")
        raise PermissionError("You do not have permission to update jobs.")

    # Start a session for updates
    async with await db.client.start_session() as session:
        async with session.start_transaction():
            try:
                # Step 1: Find the resource request owned by this HM
                resource_request = await db.resource_request.find_one(
                    {"resource_request_id": request_id, "hm_id": current_user["employee_id"]},
                    session=session  # Pass the session for atomicity
                )
                logger.info(f"Fetching the Existing Job from Resource Request Document with ID: {request_id}")
                
                if not resource_request:
                    logger.warning(f"ResourceRequest not found or unauthorized for request_id={request_id}, hm_id={current_user['employee_id']}")
                    raise PermissionError("ResourceRequest not found or you're not authorized to update this job.")
 
                # Step 2: Update ResourceRequest
                update_resource_request_data = update_data.dict(exclude_unset=True, by_alias=False)
                update_resource_request_data = normalize_dates(update_resource_request_data)
 
                update_result = await db.resource_request.update_one(
                    {"resource_request_id": request_id, "hm_id": current_user["employee_id"]},
                    {"$set": update_resource_request_data},
                    session=session
                )
                
                if update_result.matched_count == 0:
                    logger.error(f"No matching ResourceRequest found for update. request_id={request_id}, hm_id={current_user['employee_id']}")
                    raise Exception("ResourceRequest not found for the job.")

                logger.info(f"Updating the Resource Request ID: {request_id} by HM ID: {current_user['employee_id']}")
                return True
 
            except Exception as e:
                logger.error(f"Error in update_resource_request for request_id={request_id}, hm_id={current_user.get('employee_id')}: {str(e)}")
                raise Exception(f"Error occurred: {e}")
            

# Normalize skill strings by removing brackets, quotes, and extra spaces.
def clean_skill(skill: str) -> str:
    if not isinstance(skill, str):
        return str(skill).strip()
    skill = skill.strip()
    skill = skill.replace("[", "").replace("]", "")
    skill = skill.replace("'", "").replace('"', "")
    return skill.strip()


# Function to get skills availability for HM
# Fetches all resource requests for the HM, extracts all required skills,
# and returns count of employees skilled in each skill

async def get_skills_availability(current_user,resource_request_id: Optional[str] = None,skill: Optional[str] = None):
    try:
        hm_id = current_user["employee_id"]
 
        # Step 1: Fetch all resource requests for this HM
        resource_requests = await db.resource_request.find({"hm_id": hm_id}).to_list(None)
        logger.info(f"Fetched the all Resource Requests under HM ID:{hm_id}")
 
        # Step 2: Extract all unique skills
        all_skills = set()
        rr_skills_mapping = []
 
        for rr in resource_requests:
            rr_id = rr.get("resource_request_id", "")
 
            # Apply resource_request_id filter if provided
            if resource_request_id and rr_id != resource_request_id:
                logger.debug(f"Skipping resource request {rr_id} (filter applied)")
                continue
 
            mandatory_skills = rr.get("mandatory_skills", [])
            optional_skills = rr.get("optional_skills", [])
 
            if isinstance(optional_skills, str):
                optional_skills = [s.strip() for s in optional_skills.split(",") if s.strip()]
 
            mandatory_skills = [clean_skill(s) for s in mandatory_skills]
            optional_skills = [clean_skill(s) for s in optional_skills]
 
            combined_skills = list(set(mandatory_skills + optional_skills))
            all_skills.update(combined_skills)
 
            rr_skills_mapping.append({
                "resource_request_id": rr_id,
                "project_name": rr.get("project_name", ""),
                "ust_role": rr.get("ust_role", ""),
                "mandatory_skills": mandatory_skills,
                "optional_skills": optional_skills,
                "combined_skills": combined_skills,
                "total_skills_required": len(combined_skills)
            })
        logger.info(f"Extracted {len(all_skills)} unique skills across resource requests")
 
        # Step 3: For each skill, find employees
        skills_summary = []
        for skill_name in sorted(all_skills):
            if not skill_name:
                continue
 
            if skill and skill_name.lower() != skill.lower():
                logger.debug(f"Skipping skill {skill_name} (filter applied)")
                continue
 
            employees_with_skill = await db.employees.find({"detailed_skills": {"$in": [skill_name]}}).to_list(None)
 
            skills_summary.append({
                "skill": skill_name,
                "employee_count": len(employees_with_skill),
                "employees": [
                    {
                        "employee_id": emp.get("employee_id"),
                        "employee_name": emp.get("employee_name"),
                        "designation": emp.get("designation"),
                        "primary_technology": emp.get("primary_technology"),
                        "city": emp.get("city")
                    }
                    for emp in employees_with_skill
                ]
            })
 
        # Step 4: Conditional return format
        if resource_request_id and not skill:
            logger.info("Returning data with resource_request filter only")
            # Only resource request filter
            return {
                "hm_id": hm_id,
                "resource_requests": rr_skills_mapping,
                "skills_summary": skills_summary
            }
        elif skill and not resource_request_id:
            logger.info("Returning data with skill filter only")
 
            # Only skill filter
            return {
                "hm_id": hm_id,
                "skills_summary": skills_summary
            }
        elif skill and resource_request_id:
            logger.info("Returning data with both resource_request and skill filters")
 
            # Both filters applied
            return {
                "hm_id": hm_id,
                "all_unique_skills": list(all_skills),
                "resource_requests": rr_skills_mapping,
                "skills_summary": skills_summary
            }
        else:
            # No filters applied → full summary
            logger.info("Returning full summary (no filters applied)")
            return {
                "hm_id": hm_id,
                "resource_requests_count": len(resource_requests),
                "all_unique_skills": list(all_skills),
                "total_unique_skills": len(all_skills),
                "resource_requests": rr_skills_mapping,
                "skills_summary": sorted(skills_summary, key=lambda x: x["employee_count"], reverse=True),
                "summary_stats": {
                    "total_resource_requests": len(resource_requests),
                    "total_unique_skills_required": len(all_skills),
                    "average_employees_per_skill": round(
                        sum(s["employee_count"] for s in skills_summary) / len(skills_summary), 2
                    ) if skills_summary else 0,
                    "skills_with_no_employees": len([s for s in skills_summary if s["employee_count"] == 0])
                }
            }
 
    except Exception as e:
        logger.error(
            f"Error retrieving skills availability for HM ID={current_user.get('employee_id')}, "
            f"resource_request_id={resource_request_id}, skill={skill}: {str(e)}"
        )
        raise Exception(f"Error retrieving skills availability: {str(e)}")
 
    
async def patch_resource_request_single(request_id: str, key: str,value: Any,current_user: Dict) -> bool:
 
    # Step 0: Permission check
    if current_user.get("role") != "HM":
        logger.warning(f"Unauthorized patch attempt by role={current_user['role']}, hm_id={current_user['employee_id']}")
        raise PermissionError("You do not have permission to patch resource requests.")
 
 
    # Step 2: Normalize value if needed (e.g., dates)
    update_value = normalize_dates({key: value})[key]
    logger.debug(f"Normalized value for key={key}: {update_value}")

    # Step 3: Apply patch
    async with await db.client.start_session() as session:
        async with session.start_transaction():
            try:
                result = await db.resource_request.update_one(
                    {"resource_request_id": request_id, "hm_id": current_user["employee_id"]},
                    {"$set": {key: update_value}},
                    session=session
                )
 
                if result.matched_count == 0:
                    logger.error(
                            f"No matching ResourceRequest found for patch. request_id={request_id}, hm_id={current_user['employee_id']}"
                        )
                    raise PermissionError("ResourceRequest not found or not owned by this HM.")
                logger.info(f"Performed the patch on Resource Request ID : {request_id} under HM ID:{current_user['employee_id']}")
                return True

            except Exception as e:
                logger.error(
                        f"Error while patching ResourceRequest ID={request_id}, hm_id={current_user['employee_id']}, key={key}: {str(e)}"
                    )
                raise Exception(f"Error occurred while patching ResourceRequest: {e}")
        
        
async def delete_resource_request(
    request_id: str,
    current_user: Dict
) -> bool:

    # Step 0: Permission check
    if current_user.get("role") != "HM":
        logger.warning(f"Unauthorized delete attempt by role={current_user['role']}, hm_id={current_user['employee_id']}")
        raise PermissionError("You do not have permission to delete resource requests.")
 
    async with await db.client.start_session() as session:
        async with session.start_transaction():
            try:
                result = await db.resource_request.update_one(
                    {"resource_request_id": request_id, "hm_id": current_user["employee_id"]},
                    {"$set": {"flag": False}},   # mark as inactive
                    session=session
                )

                if result.matched_count == 0:
                    raise PermissionError("ResourceRequest not found or not owned by this HM.")
               
                logger.info(f"Deactivating the Resource Request ID : {request_id} under HM ID:{current_user['employee_id']}")
 
                return True
 
            except Exception as e:
                logger.error(
                        f"Error while deleting ResourceRequest ID={request_id}, hm_id={current_user['employee_id']}: {str(e)}"
                    )
                raise Exception(f"Error occurred while deleting ResourceRequest: {e}")