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
 

class Employee(BaseModel):
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
 
    # Normalize TP / Non TP
    @field_validator("type", mode="before")
    @classmethod
    def normalize_type(cls, v):
        if not v:
            return "Non TP"
        return "TP" if str(v).strip().upper() == "TP" else "Non TP"
 
    # Validate and normalize band values
    @field_validator("band", mode="before")
    @classmethod
    def normalize_band(cls, v):
        if not v or str(v).strip() == "":
            return None
 
        value = str(v).strip().upper()
 
        if re.match(r"^[A-D][0-9]$", value):    # A0–D9
            return value
        if re.match(r"^[TEP][0-9]$", value):    # T/E/P grades
            return value
 
        raise ValueError(f"Invalid band format: '{value}'")
 
    # Handle NA/Not Available
    @field_validator("primary_technology", "secondary_technology", mode="before")
    @classmethod
    def handle_not_available(cls, v, info):
        if not v or str(v).strip().upper() in ("NOT AVAILABLE", "NA", "NULL", ""):
            return "" if info.field_name == "primary_technology" else None
        return str(v).strip()
 
    # Split comma-separated or question-mark-separated skills
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
 
 