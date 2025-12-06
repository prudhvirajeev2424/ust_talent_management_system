# ----------------------------- IMPORTS -----------------------------
from pydantic import BaseModel, field_validator, Field, AwareDatetime
import re
from typing import List, Optional,Literal
from datetime import datetime,date,timedelta
from enum import Enum
import uuid
from bson import ObjectId
from pydantic import BaseModel, field_validator, Field, AwareDatetime
import re
from typing import List, Optional,Literal
from datetime import date, datetime, timezone
 
# ----------------------------- USER MODEL -----------------------------
class User(BaseModel):
    # Employee identifier for authentication
    employee_id : str
    # Default hashed password assigned
    password : str = "$argon2id$v=19$m=65536,t=3,p=4$otQ6h9CaM4ZwzlnL2TtnTA$gbLxVjVlKj/NYp7KF7B287JDOVMMHO3oDGUbjszW32U"
    # User role (Admin / HM / etc.)
    role : str
    # Whether the account is active
    is_active : bool = True
    # Time of creation stored in UTC
    created_at : datetime = datetime.now(timezone.utc)
   
 
# ----------------------------- EMPLOYEE MODEL -----------------------------
class Employee(BaseModel):
    # Mapped fields from Excel columns using alias
    employee_id: int = Field(..., alias="Employee ID")
    employee_name: str = Field(..., alias="Employee Name")
    employment_type: str = Field(..., alias="Employment Type")
    designation: str = Field(..., alias="Designation")
    band: Optional[str] = Field( alias="Band")
    city: str = Field(..., alias="City")
    location_description: str = Field(..., alias="Location Description")
    primary_technology: str = Field(..., alias="Primary Technology")
    secondary_technology: Optional[str] = Field(None, alias="Secondary Technology")
    detailed_skills: List[str] = Field(default_factory=list,
                                       alias="Detailed Skill Set (List of top skills on profile)")
    type: Literal["TP", "Non TP"] = Field(..., alias="Type")
    resume : Optional[str] = None
    resume_text: Optional[str] = Field(None)
 
    # Normalize TP / Non TP values
    @field_validator("type", mode="before")
    @classmethod
    def normalize_type(cls, v):
        if not v:
            return "Non TP"
        return "TP" if str(v).strip().upper() == "TP" else "Non TP"
 
    # Validate band format
    @field_validator("band", mode="before")
    @classmethod
    def normalize_band(cls, v):
        if not v or str(v).strip() == "":
            return None
 
        value = str(v).strip().upper()
 
        if re.match(r"^[A-D][0-9]$", value):
            return value
        if re.match(r"^[TEP][0-9]$", value):
            return value
 
        raise ValueError(f"Invalid band format: '{value}'")
 
    # Normalize NA-like text for tech fields
    @field_validator("primary_technology", "secondary_technology", mode="before")
    @classmethod
    def handle_not_available(cls, v, info):
        if not v or str(v).strip().upper() in ("NOT AVAILABLE", "NA", "NULL", ""):
            return "" if info.field_name == "primary_technology" else None
        return str(v).strip()
 
    # Convert comma-separated skills into list
    @field_validator("detailed_skills", mode="before")
    @classmethod
    def split_detailed_skills(cls, v):
        if not v or str(v).strip().upper() in ("NA", "NOT AVAILABLE", "NULL", ""):
            return []
        list_v = str(v).strip().split(",")
        return [v.strip() for v in list_v]
 
    class Config:
        populate_by_name = False
        extra = "ignore"
 
# ----------------------------- RESOURCE REQUEST MODEL -----------------------------
class ResourceRequest(BaseModel):
    # All fields mapped using aliases from RR Excel
    resource_request_id: str = Field(..., alias="Resource Request ID")
    rr_fte: float = Field(..., alias="RR FTE")
    allocated_fte: Optional[float] = Field(None, alias="Allocated FTE")
    rr_status: Literal["Approved", "Cancelled", "Closed", "EDIT REQUEST APPROVED"] = Field(..., alias="RR Status")
    rr_type: Literal["New Project", "Existing Project", "Replacement", "Attrition"] = Field(..., alias="RR Type")
    priority: str = Field(..., alias="Priority")
    ust_role: str = Field(..., alias="UST - Role")
    city: str = Field(..., alias="City")
    state: Optional[str] = Field(None, alias="State")
    country: str = Field(..., alias="Country")
    alternate_location: Optional[str] = Field(None, alias="Altenate Location")
    campus: str = Field(..., alias="Campus")
    job_grade: str = Field(..., alias="Job Grade")
    rr_start_date: date = Field(..., alias="RR Start Date")
    rr_end_date: date = Field(..., alias="RR End Date")
    account_name: str = Field(..., alias="Account Name")
    project_id: str = Field(..., alias="Project ID")
    project_name: str = Field(..., alias="Project Name")
    wfm: str = Field(..., alias="WFM")
    wfm_id: str = Field(..., alias="WFM ID")
    hm: str = Field(..., alias="HM")
    hm_id: str = Field(..., alias="HM ID")
    am: str = Field(..., alias="AM")
    am_id: str = Field(..., alias="AM ID")
    billable: Literal["Yes", "No"] = Field(..., alias="Billable")
    actual_bill_rate: Optional[float] = Field(None, alias="Actual Bill Rate")
    actual_currency: Optional[str] = Field(None, alias="Actual Currency")
    bill_rate: Optional[float] = Field(None, alias="Bill Rate")
    billing_frequency: Optional[Literal["H", "D", "M", "Y"]] = Field(None, alias="Billing Frequency")
    currency: Optional[str] = Field(None, alias="Currency")
    target_ecr: Optional[float] = Field(None, alias="Target ECR")
    accepted_resource_type: Optional[str] = Field("Any", alias="Accepted Resource Type")
    replacement_type: Optional[str] = Field(None, alias="Replacement Type")
    exclusive_to_ust: bool = Field(..., alias="Exclusive to UST")
    contract_to_hire: bool = Field(..., alias="Contract to Hire")
    client_job_title: Optional[str] = Field(None, alias="Client Job Title")
    ust_role_description: Optional[str] = Field(..., alias="UST Role Description")
    job_description: Optional[str] = Field(..., alias="Job Description")
    notes_for_wfm_or_ta: Optional[str] = Field(None, alias="Notes for WFM or TA")
    client_interview_required: Literal["Yes", "No"] = Field(..., alias="Client Interview Required")
    obu_name: str = Field(..., alias="OBU Name")
    project_start_date: date = Field(..., alias="Project Start Date")
    project_end_date: date = Field(..., alias="Project End Date")
    raised_on: date = Field(..., alias="Raised On")
    rr_finance_approved_date: Optional[date] = Field(None, alias="RR Finance Approved Date")
    wfm_approved_date: Optional[date] = Field(alias="WFM Approved Date")
    cancelled_reasons: Optional[str] = Field(None, alias="Cancelled Reasons")
    edit_requested_date: Optional[date] = Field(None, alias="Edit Requested Date")
    resubmitted_date: Optional[date] = Field(None, alias="Resubmitted Date")
    duration_in_edit_days: Optional[int] = Field(None, alias="Duration in Edit(Days)")
    number_of_edits: Optional[int] = Field(None, alias="# of Edits")
    resubmitted_reason: Optional[str] = Field(None, alias="Resubmitted Reason")
    comments: Optional[str] = Field(None, alias="Comments")
    recruiter_name: Optional[str] = Field(None, alias="Recruiter Name")
    recruiter_id: Optional[str] = Field(None, alias="Recruiter ID")
    recruitment_type: Optional[str] = Field(None, alias="Recruitment Type")
    project_type: Literal["T&M", "Non T&M"] = Field(..., alias="Project Type")
    last_updated_on: date = Field(..., alias="Last Updated On")
    last_activity_date: AwareDatetime = Field(..., alias="Last Activity Date")
    last_activity: Optional[str] = Field(None, alias="Last Activity")
    contract_category: Optional[str] = Field(None, alias="Contract Category")
    mandatory_skills: List[str] = Field(..., alias="Mandatory Skills")
    optional_skills: Optional[List[str]] = Field(None, alias="Optional Skills")
    rr_skill_group: Optional[List[str]] = Field(None, alias="RR Skill Group")
    flag: bool = True  
    matching_resources_count: Optional[int] = Field(None, alias="Matching Resources Count (Score 50% and above)")
    hiring_request_submit_date_mte: Optional[date] = Field(None, alias="Hiring request Submit Date (MTE)")
    marked_to_external: Optional[str] = Field(None, alias="Marked To External")
    mte_status: Optional[str] = Field(None, alias="MTE Status")
    external_system: Optional[str] = Field(None, alias="External - System")
    so_initiator_name: Optional[str] = Field(None, alias="SO Initiator Name")
    so_initiator_id: Optional[str] = Field(None, alias="SO Initiator ID")
    external_status: Optional[str] = Field(None, alias="External Status")
    allocation_project_id: Optional[str] = Field(None, alias="Allocation Project ID")
    allocation_project_start_date: Optional[date] = Field(None, alias="Allocation Project Start Date")
    allocation_project_end_date: Optional[date] = Field(None, alias="Allocation Project End Date")
    practice_line: Optional[str] = Field(None, alias="Practice Line")
    ta_cluster_lead: Optional[str] = Field(None, alias="TA Cluster Lead")
    rr_ageing: Optional[int] = Field(None, alias="RR Ageing")
    duration_before_cancellation: Optional[int] = Field(None, alias="Duration before Cancellation")
    resources_in_propose: Optional[int] = Field(None, alias="Resources in Propose")
    resources_in_hm_check: Optional[int] = Field(None, alias="Resources in HM Check")
    resources_in_internal_interview: Optional[int] = Field(None, alias="Resources in Internal Interview")
    resources_in_customer_interview: Optional[int] = Field(None, alias="Resources in Customer Interview")
    resources_in_accept: Optional[int] = Field(None, alias="Resources in Accept")
    resources_in_allocated: Optional[int] = Field(None, alias="Resources in Allocated")
    resources_in_not_allocated: Optional[int] = Field(None, alias="Resources in Not Allocated")
    resources_in_reject: Optional[int] = Field(None, alias="Resources in Reject")
    edits_requested: Optional[str] = Field(None, alias="Edits Requested")
    outgoing_employee_id: Optional[str] = Field(None, alias="Outgoing Employee Id")
    outgoing_employee_name: Optional[str] = Field(None, alias="Outgoing Employee Name")
    cancel_requested: Optional[str] = Field(None, alias="Cancel Requested")
    legal_entity: str = Field(..., alias="Legal Entity")
    company_name: str = Field(..., alias="Company Name")
 
    # Convert numeric-like CSV strings to numbers
    @field_validator("allocated_fte","duration_before_cancellation","resources_in_propose",
"resources_in_hm_check",
"resources_in_internal_interview",
"resources_in_customer_interview",
"resources_in_accept",
"resources_in_allocated",
"resources_in_not_allocated",
"resources_in_reject","rr_ageing",mode="before")
    @classmethod
    def csv_str_to_float(cls,v):
        if str(v).strip() == "" or v==None:
            return
        v = float(str(v).strip())
        return v
    @field_validator("duration_in_edit_days","number_of_edits",mode="before")
    @classmethod
    def csv_str_to_int(cls,v):
        if str(v).strip() == "" or v==None:
            return
        v = int(str(v).strip())
        return v
    # Normalize priority to P1–P4
    @field_validator("priority", mode="after")
    @classmethod
    def normalize_priority(cls, v):
        v = str(v).strip().upper()
        return v if v in ("P1", "P2", "P3", "P4") else "P4"
 
    # Convert yes-like values to bool
    @field_validator("exclusive_to_ust", "contract_to_hire", mode="before")
    @classmethod
    def str_to_bool(cls, v):
        if isinstance(v, bool):
            return v
        return str(v).strip().upper() in ("TRUE", "YES", "Y", "1")
 
    # Convert CSV skill strings into clean lists
    @field_validator("mandatory_skills", "optional_skills","rr_skill_group", mode="before")
    @classmethod
    def split_skills_from_string(cls, v):
        if not v or str(v).strip().upper() in ("", "NA", "N/A"):
            return []
        if str(v).startswith("[") and str(v).endswith("]"):
            v = str(v)[1:-1]
        return [item.strip() for item in str(v).split(",") if item.strip()]
 
    # Parse multiple date fields from mixed formats
    @field_validator(
        "rr_start_date", "rr_end_date", "project_start_date", "project_end_date",
        "raised_on", "last_updated_on", "rr_finance_approved_date", "wfm_approved_date",
        "edit_requested_date", "resubmitted_date","allocation_project_start_date","hiring_request_submit_date_mte","allocation_project_end_date",
        mode="before", check_fields=False
    )
    @classmethod
    def validate_rr_start_date(cls, v):
        if isinstance(v, date):
            return v
 
        v = str(v).strip()
        if v.lower() in ("", "none"):
            return None
 
        try:
            return datetime.strptime(v, "%d %b %Y").date()
        except:
            pass
 
        try:
            return datetime.fromisoformat(v.replace(" ", "T")).date()
        except:
            pass
 
        raise ValueError(f"Invalid date format '{v}'")
 
    # Parse last activity datetime across different formats
    @field_validator("last_activity_date", mode="before")
    @classmethod
    def parse_last_activity_date(cls, v):
        if not v or str(v).strip().lower() == "none":
            return None
 
        if isinstance(v, datetime):
            return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v
 
        raw = str(v).strip()
        cleaned = raw.split("(")[0].strip().rstrip(",")
 
        for fmt in ("%d %b %Y, %I:%M %p", "%d %b %Y %I:%M %p", "%d %b %Y %H:%M:%S"):
            try:
                dt = datetime.strptime(cleaned, fmt)
                return dt.replace(tzinfo=timezone.utc)
            except:
                continue
 
        try:
            dt = datetime.fromisoformat(cleaned)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except:
            pass
 
        raise ValueError(f"Invalid datetime '{v}'")
 
    class Config:
        populate_by_name = True
        extra = "ignore"

# ----------------------------- APPLICATION STATUS ENUM -----------------------------
class ApplicationStatus(str, Enum):
    # Possible application lifecycle stages
    DRAFT = "Draft"
    SUBMITTED = "Submitted"
    SHORTLISTED = "Shortlisted"
    INTERVIEW = "Interview"
    SELECTED = "Selected"
    REJECTED = "Rejected"
    ALLOCATED = "Allocated"
    WITHDRAWN = "Withdrawn"

# ----------------------------- APPLICATION MODEL -----------------------------
class Application(BaseModel):
    # MongoDB-like UUID identifier
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), alias="_id")
    # Employee applying
    employee_id: int
    # RR they applied for
    job_rr_id: str
    # Current application state
    status: ApplicationStatus = ApplicationStatus.DRAFT
    # Optional resume link/path
    resume: Optional[str] = None
    # Optional cover letter
    cover_letter: Optional[str] = None
    # When submitted (None if draft)
    submitted_at: Optional[datetime] = None
    # Timestamp auto-updated
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class ForgotPasswordRequest(BaseModel):
    email:str

class verifyCodeRequest(BaseModel):
    email:str
    code:str

class ResetPasswordRequest(BaseModel):
    email:str
    code:str
    new_password:str