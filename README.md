# Talent Management System

##  Overview
The Talent Management System is designed to streamline employee-job workflows across multiple roles (Admin, Employee, Talent Pool Manager, Workforce Manager, Hiring Manager). It ensures smooth handling of job postings, applications, shortlisting, interviews, and allocations with secure authentication and audit trails.

---

##  Roles & Responsibilities

### 1. Admin
- Upload employee data (Career Velocity Report).
- Upload job data (RR Report).
- Validate files and ensure data is clean.
- Keep system updated with latest employee and job details.

### 2. Employee (TP or Non-TP)
- View jobs relevant to them.
- Create applications (Draft -> Submitted).
- Upload resume and cover letter.
- Withdraw application (before Shortlisted stage).
- Track application status.


### 3. Talent Pool Manager (TP Manager)
- View all TP employees.
- Shortlist TP applications (Submitted -> Shortlisted).


### 4. Workforce Manager (WFM)
- View jobs mapped to them.
- Handle Non-TP applications: Submitted -> Shortlisted -> Interview -> Select/Reject.
- Handle TP applications (after TP Manager shortlists): Shortlisted -> Interview -> Select/Reject.

### 5. Hiring Manager (HM)
- Create new jobs.
- Update job details.
- Mark jobs as expired or fulfilled.
- Allocate selected employees to jobs (final step).



## Workflow Summary
1. Employee applies.  
2. TP Manager or WFM shortlists.  
3. WFM interviews & selects/rejects.  
4. Hiring Manager allocates.  
5. Job fulfilled.  



## Services

### 1. File Upload Service
- Upload Career Velocity Report (employees) & RR Report (jobs).
- Validate file type, sheet names, required columns.
- Clean data: remove duplicates, normalize text, flag missing fields.
- Store data in DB tables (Employees, Jobs, RR Audit).
- RR Report logic:
  - Add new `rr_id` (e.g., SO123_1).
  - Match existing `rr_id` for continuity.
  - Flag missing `rr_id` → mark jobs closed.
- **Audit trail:** log uploads with timestamp, file name, errors.

**Validations:**
- Allowed file types: `.xlsx`, `.csv`
- Required columns present
- `rr_id` format `<so_id>_<opening>`
- Consistent date formats

---

### 2. Job Management Service

- Create/Update/Delete jobs (HM only).
- Role-based job viewing:
  - Admin: all jobs
  - TP Employee: jobs within +1 or -1  band
  - Non-TP Employee: jobs matching filters (location/skills)
  - WFM: jobs mapped to them
  - HM: jobs mapped to them (can modify/expire/fulfill)
- Filters: location, skills, domain, band, dates, status.
- RR integration: auto-close jobs if `rr_id` missing.
- Supports multiple openings per `so_id`.

**Key Fields:**  

`job_id`, `title`, `description`, `location`, `required_skills[]`, `band`, `domain`, `rr_id`, `rr_start_date`, `rr_end_date`, `wfm_id`, `hm_id`, `status`

---

### 3. Employee Management Service

- Upload resumes (`.doc`, `.docx`, `.pdf`).
- Parse resumes → extract skills, roles, experience, certifications.
- Search/filter employees by type, skills, domain, role, location, band, availability.
- Visibility:

  - WFM: employees who applied to their jobs.
  - HM: employees allocated to their jobs.
  - TP Manager: all TP employees.

**Validations:**
- Resume types allowed: `.doc`, `.docx`, `.pdf`
- Handle parsing errors gracefully
- Normalize skills (e.g., “JS” → “JavaScript”)

---

### 4. Employee Application Service

- Create applications (Draft -> Submitted).
- Edit/withdraw drafts anytime.
- Withdraw submitted apps until Shortlisted stage.
- Attach resume & cover letter.
- Track applications by job, stage, date.

**Rules:**
- Multiple applications allowed.
- No edits after Submitted but we can withdraw our application before Shortlisted.
- Prevent duplicate active applications to same job.

---

### 5. Manager Application Workflow Service
- **TP Manager (TP application only):**
  - Submitted -> Shortlisted

- **WFM (Non-TP + TP after shortlist):**
  - Non-TP: Submitted -> Shortlisted -> Interview -> Select/Reject
  - TP: Shortlisted -> Interview -> Select/Reject

- **Hiring Manager:**
  - Allocate: Selected -> Allocated
  - Mark job fulfilled when openings filled

**Common Features:**
- Search/filter/sort by job, skills, stage, date.
- Bulk actions (e.g., shortlist multiple).
- Audit logs for every state change.

**Validations:**
- Role must match job’s `wfm_id` or `hm_id`.
- Legal stage transitions only.
- HM allocates only if status = Selected.
- Selection/rejection must capture reason.


### 6. Authentication Service
- Login with username/password or employee_id/password.
- Tokens:
  - Access Token (JWT): short-lived (-5 min).
  - Refresh Token (JWT): long-lived (-1 day).
- Refresh flow: exchange refresh token for new access token.
- Role-based authorization.
- Logout/revoke refresh tokens.
- Log login attempts, failures, token usage.


## Cross-Cutting Features
- Role-based access control (RBAC).
- Audit logs for all actions.
- Clear error handling.
- Notifications (optional).
- Rate limiting for sensitive endpoints.
- Idempotency for uploads & state changes.

---

## Typical End-to-End Flow
1. Admin uploads Employee & RR reports -> data stored, jobs synced.  
2. Hiring Manager creates/edits jobs -> jobs visible to employees.  
3. Employee applies (Draft -> Submitted).  
4. TP Manager/WFM process applications -> shortlist -> interview -> select/reject.  
5. Hiring Manager allocates selected candidates -> job fulfilled/closed.  
6. All users see role-based views with search/filter/sort.  

---

## Tech Notes
- Backend: Microservices architecture.
- Authentication: JWT-based.
- Data storage: Relational DB (Employees, Jobs, RR Audit).
- File handling: Excel/CSV for reports, DOC/PDF for resumes.
- Audit & logging across all services.

## **Setup and Installation**

### 1. Clone the Repository

Start by cloning the repository to your local machine:

```bash
git clone https://github.com/prudhvirajeev2424/ust_talent_management_system.git
cd ust_talent_management_system
```

### 2. Install Dependencies.

Install all required dependencies in your environment.

```bash
pip install -r requirements.txt
```

### 3. Configure MongoDB Connection

#### MongoDB Connection:
- Set up a MongoDB Atlas account (if you haven't already) and create a cluster.
- In the project root, create a `.env` file and add the MongoDB URI:
  
  ```env
  DB_URI=mongodb+srv://303391_db_user:5IhrghdRaiXTR22b@cluster0.i0ih74y.mongodb.net/?appName=Cluster0
  ```

### 4. Start the Server Using Uvicorn

Once the setup is complete, you can start the FastAPI application using Uvicorn.

Run the following command to start the server in development mode (with auto-reload enabled):

```bash
uvicorn main:app --reload
```

### 5. Verify the Application

Once the server is running, navigate to `http://127.0.0.1:8000` in your browser to confirm that the application is running.

- **Swagger Docs**: FastAPI provides auto-generated documentation. Go to `http://127.0.0.1:8000/docs` to view the interactive API docs.
- **Redoc Docs**: You can also access the API documentation in Redoc format at `http://127.0.0.1:8000/redoc`.
