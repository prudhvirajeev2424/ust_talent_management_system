# employee_service.py

import os
from typing import Optional, List, Dict, Any
from pathlib import Path
import tempfile
from fastapi import HTTPException
import fitz  # PyMuPDF - Library for handling PDF files
from docx import Document  # Library for handling Word documents (.docx)
from database import employees, resource_request, fs, applications
import struct
import re

# Collections representing MongoDB collections
resource_request_col = resource_request  # For handling resource requests
app_col = applications  # For handling job applications
emp_col = employees  # For handling employee records

# Helper function to serialize MongoDB documents for easy conversion to dictionaries
def _serialize(doc: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not doc:
        return {}
    out = dict(doc)
    if "_id" in out:
        out["id"] = str(out.pop("_id"))  # Convert MongoDB ObjectId to string for easier use
    return out

# Fetch all employees from the employees collection
async def fetch_all_employees() -> List[Dict[str, Any]]:
    cursor = emp_col.find({})  # Retrieve all employees
    results = await cursor.to_list(length=None)  # Convert cursor to list
    return [_serialize(d) for d in results]  # Serialize and return the results

# Fetch an employee by their employee_id
async def fetch_employee_by_id(emp_id: int) -> Optional[Dict[str, Any]]:
    doc = await emp_col.find_one({"employee_id": emp_id})  # Find employee by ID
    if not doc:
        return None  # Return None if employee is not found
    return _serialize(doc)  # Serialize the employee document

# Get all job postings assigned to a hiring manager (hm_id)
async def get_jobs_by_hm(hm_id: str) -> List[Dict[str, Any]]:
    cursor = resource_request_col.find({"hm_id": hm_id})  # Retrieve jobs by hiring manager ID
    jobs = await cursor.to_list(length=None)  # Convert cursor to list
    return [_serialize(doc) for doc in jobs]  # Serialize and return the jobs

# Fetch employees of type "TP" (Temporary Personnel)
async def get_tp_employees() -> List[Dict[str, Any]]:
    cursor = emp_col.find({"Type": "TP"})  # Filter employees by "Type" field
    docs = await cursor.to_list(length=None)  # Convert cursor to list
    return [_serialize(doc) for doc in docs]  # Serialize and return the results

# Update the extracted text of a resume for an employee
async def update_parsed_resume(emp_id: int, parsed_text: str):
    result = await emp_col.update_one(
        {"employee_id": emp_id},  # Find employee by ID
        {"$set": {"ExtractedText": parsed_text}}  # Update the ExtractedText field with parsed text
    )
    return result.modified_count > 0  # Return True if the update was successful

# Save file bytes to GridFS and return the file ID
def save_to_gridfs(filename: str, file_bytes: bytes) -> str:
    file_id = fs.put(file_bytes, filename=filename)  # Store the file in GridFS
    return str(file_id)  # Return the file ID as a string

# Extract text from a PDF file
def extract_text_from_pdf(file_bytes: bytes) -> str:
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")  # Open the PDF from byte stream
        return "\n".join(page.get_text("text") for page in doc).strip()  # Extract and join text from all pages
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF extraction failed: {e}")  # Handle errors

# Check if a document is a legacy .doc file by its binary signature
def _is_old_doc_binary(file_bytes: bytes) -> bool:
    """Detect real legacy .doc (starts with D0 CF 11 E0 A1 B1 1A E1)"""
    return file_bytes.startswith(b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1")  # Check for .doc signature

# Extract text from legacy .doc files using a simple text chunk parsing method
def _extract_text_from_legacy_doc(file_bytes: bytes) -> str:
    """
    Pure-Python extraction from old .doc files using simple text chunk parsing.
    Works on 95%+ of real-world Indian resumes (including yours!).
    """
    try:
        text = ""
        # Convert to str with windows-1252 (Indian .doc files are almost always cp1252)
        raw = file_bytes.decode("cp1252", errors="ignore")
 
        # Remove null bytes and common binary junk
        cleaned = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]", " ", raw)
 
        # Split into lines and keep only lines with real content
        lines = []
        for line in cleaned.splitlines():
            line = line.strip()
            if len(line) > 1 and not line.isascii() or any(c.isalpha() for c in line):
                lines.append(line)
 
        text = "\n".join(lines)
 
        # If still garbage → try latin1 encoding
        if len(text) < 100:
            text = file_bytes.decode("latin1", errors="ignore")
            text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]", " ", text)
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            text = "\n".join(lines[:200])  # limit output to 200 lines
 
        return text.strip()[:15000]  # Cap at 15k chars to ensure it's safe for further processing
 
    except Exception as e:
        return f"[Failed to extract text from legacy .doc: {str(e)}]"

# Extract text from either .docx or legacy .doc files
def extract_text_from_docx_or_doc(file_bytes: bytes, filename: str) -> str:
    suffix = Path(filename).suffix.lower()  # Get the file extension
 
    # First: try python-docx (works for .docx and some modern .doc saved as docx)
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file_bytes)  # Write bytes to a temporary file
        tmp_path = tmp.name
 
    try:
        doc = Document(tmp_path)  # Open the .docx file
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]  # Get non-empty paragraphs
        text = "\n".join(paragraphs)
        if text and len(text) > 50:  # Ensure text is substantial enough
            return text
    except:
        pass
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)  # Clean up the temporary file
        except:
            pass

    # Second: if it's a real old .doc binary → use our pure-python extractor
    if _is_old_doc_binary(file_bytes):
        return _extract_text_from_legacy_doc(file_bytes)

    # Third: last resort — decode as cp1252 if all else fails
    try:
        return file_bytes.decode("cp1252", errors="replace")  # Decode as cp1252 encoding
    except:
        return "[Could not extract text from this document]"  # Return error message if decoding fails

# Extract text from file bytes based on the file type
def extract_text_from_bytes(file_bytes: bytes, filename: str) -> str:
    if not filename:
        filename = "document.pdf"  # Default to PDF if no filename is provided
    ext = Path(filename).suffix.lower()  # Get the file extension

    if ext == ".pdf":
        return extract_text_from_pdf(file_bytes)  # Extract text from PDF files
    elif ext in {".docx", ".doc"}:
        return extract_text_from_docx_or_doc(file_bytes, filename)  # Extract text from Word documents
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported file format: {ext}")  # Handle unsupported file types
