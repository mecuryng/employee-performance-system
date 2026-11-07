# Employee Performance System

Progressive employee performance evaluation with an explainable, rule-based HR recommendation engine.

## Current foundation

- FastAPI backend with health, authentication, and performance-evaluation endpoints
- Admin-managed accounts with admin, HR, supervisor, and employee roles
- Department and employee directory management with supervisor relationships
- Admin and HR configuration of KPIs and dated evaluation periods
- Employee self-assessments and direct-supervisor assessments, linked to dated periods
- Explainable rule-based recommendations with HR approval or rejection
- HR dashboard summaries, downloadable period reports, audit events, and assessment evidence links
- Signed bearer access tokens and PBKDF2 password hashing
- Streamlit frontend shell
- PostgreSQL schema foundation
- Weighted KPI score calculation with performance-gap detection
- Initial automated tests

## Run the backend

From `backend/` after installing the requirements and configuring `DATABASE_URL` and `JWT_SECRET` in the project `.env` file:

```powershell
uvicorn app.main:app --reload
```

Set a long, random `JWT_SECRET` before running outside local development. The API is available at `http://127.0.0.1:8000` and its documentation at `/docs`.

Create the first administrator from `backend/`:

```powershell
python create_admin.py
```

Sign in at `POST /api/v1/auth/login` and send the returned token as `Authorization: Bearer <token>`. Use `POST /api/v1/auth/users` with an admin token to create accounts. Employee and supervisor accounts require an `employee_id` linking them to an employee directory record. `GET /api/v1/auth/me` returns the signed-in user.

Admins and HR manage recommendation rules at `/api/v1/recommendation-rules`. Generate recommendations at `/api/v1/employees/{employee_id}/periods/{period_id}/recommendations`. Generation requires a supervisor assessment and positive KPI default weights. HR can list results at `/api/v1/recommendations` and approve or reject one at `/api/v1/recommendations/{recommendation_id}/review`. Rules can match overall score thresholds, KPI gaps, and disagreement between self and supervisor scores. Saved recommendations include the matched action, explanation, and input context.

Employees can submit one self-assessment per open period; supervisors can submit one assessment per direct report. Admins and HR can review all submissions, supervisors can review their direct reports, and employees can review their own. Performance evaluation requires admin, HR, or supervisor role. HR/admins manage departments, employees, KPIs, and evaluation periods. HR/admins can read period summaries at `/api/v1/dashboard/periods/{period_id}`, download CSV reports at `/api/v1/reports/periods/{period_id}.csv`, and query audit events at `/api/v1/audit-events`. Assessment evidence notes and optional HTTP(S) source links can be added at `/api/v1/assessments/{assessment_id}/evidence`; access follows the assessment visibility rules.

## Run the frontend

```powershell
streamlit run frontend/app.py
```

## Development sequence

1. Authentication and role-based access control
2. Employee and department management
3. KPI configuration and evaluation periods
4. Self-assessment and supervisor assessment workflows (implemented)
5. Explainable recommendation rules and HR review (implemented)
6. Dashboards, reports, audit history, and evaluation evidence (implemented)












