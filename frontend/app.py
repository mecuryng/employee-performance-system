"""Streamlit client for the Employee Performance System API."""
from __future__ import annotations

import json
import os
from datetime import date
from typing import Any

import httpx
import streamlit as st

st.set_page_config(page_title="Employee Performance System", page_icon="📊", layout="wide")

API_URL = os.getenv("API_URL", "http://127.0.0.1:8000/api/v1").rstrip("/")
ROLE_LABELS = {"admin": "Administrator", "hr": "HR", "supervisor": "Supervisor", "employee": "Employee"}


class APIError(Exception):
    pass


def api(method: str, path: str, *, params: dict | None = None, body: dict | None = None) -> Any:
    headers = {}
    token = st.session_state.get("token")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = httpx.request(method, f"{API_URL}{path}", params=params, json=body, headers=headers, timeout=20)
    except httpx.HTTPError as exc:
        raise APIError(f"Could not reach the API at {API_URL}: {exc}") from exc
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise APIError(f"{response.status_code}: {detail}")
    if response.status_code == 204 or not response.content:
        return None
    if "text/csv" in response.headers.get("content-type", ""):
        return response.content
    return response.json()


def call(method: str, path: str, *, params: dict | None = None, body: dict | None = None, success: str = "Saved.") -> Any:
    try:
        result = api(method, path, params=params, body=body)
        st.success(success)
        return result
    except APIError as exc:
        st.error(str(exc))
        return None


def load(path: str, *, params: dict | None = None) -> list | dict | None:
    try:
        return api("GET", path, params=params)
    except APIError as exc:
        st.error(str(exc))
        return None


def login_screen() -> None:
    st.title("Employee Performance System")
    st.caption("Performance reviews, recommendations, and reporting")
    with st.form("login"):
        st.subheader("Sign in")
        email = st.text_input("Email", autocomplete="email")
        password = st.text_input("Password", type="password", autocomplete="current-password")
        submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)
    if submitted:
        try:
            result = api("POST", "/auth/login", body={"email": email, "password": password})
            st.session_state.token = result["access_token"]
            st.session_state.user = api("GET", "/auth/me")
            st.rerun()
        except APIError as exc:
            st.error(str(exc))
    st.caption(f"API: {API_URL}")


def options(records: list[dict], label) -> tuple[list[str], dict[str, dict]]:
    keyed = {str(item["id"]): item for item in records}
    labels = [label(item) for item in records]
    return labels, {label(item): item for item in records}


def assessment_form(kind: str, employee_id: str | None = None) -> None:
    periods = load("/evaluation-periods") or []
    kpis = load("/kpis") or []
    if not periods or not kpis:
        st.info("An active evaluation period and KPI configuration are required before submitting an assessment.")
        return
    period_labels, period_map = options(periods, lambda p: f"{p['name']} ({p['start_date']} to {p['end_date']})")
    with st.form(f"assessment-{kind}-{employee_id or 'self'}"):
        period_label = st.selectbox("Evaluation period", period_labels)
        comments = st.text_area("Overall comments", max_chars=4000)
        st.markdown("#### KPI scores")
        scores = []
        for kpi in kpis:
            with st.container(border=True):
                st.markdown(f"**{kpi['name']}** · `{kpi['code']}`")
                st.caption(kpi["description"])
                score = st.slider(f"Score · {kpi['code']}", 0, 100, 70, key=f"{kind}-{employee_id}-{kpi['id']}")
                comment = st.text_input(f"Evidence / comment · {kpi['code']}", key=f"comment-{kind}-{employee_id}-{kpi['id']}", max_chars=1000)
                scores.append({"kpi_id": kpi["id"], "score": score, "comment": comment})
        submitted = st.form_submit_button("Submit assessment", type="primary")
    if submitted:
        path = "/assessments/self" if kind == "self" else f"/assessments/supervisor/{employee_id}"
        result = call("POST", path, body={"period_id": period_map[period_label]["id"], "comments": comments, "scores": scores}, success="Assessment submitted.")
        if result:
            st.rerun()


def assessment_table(items: list[dict], allow_evidence: bool = True) -> None:
    if not items:
        st.info("No assessments found.")
        return
    st.dataframe([{"Type": a["assessment_type"].title(), "Employee": a["employee_id"], "Period": a["period_id"], "Submitted": a["submitted_at"], "Comments": a["comments"]} for a in items], use_container_width=True, hide_index=True)
    with st.expander("Assessment details and evidence"):
        ids = {f"{a['assessment_type'].title()} · {a['submitted_at']} · {a['id'][:8]}": a for a in items}
        selected = st.selectbox("Assessment", list(ids))
        assessment = ids[selected]
        st.write(assessment.get("comments") or "No overall comments.")
        st.dataframe([{"KPI": s["kpi_id"], "Score": float(s["score"]), "Comment": s["comment"]} for s in assessment["scores"]], use_container_width=True, hide_index=True)
        if not allow_evidence:
            return
        evidence = load(f"/assessments/{assessment['id']}/evidence") or []
        if evidence:
            st.markdown("**Evidence**")
            for item in evidence:
                st.write(f"**{item['title']}** — {item['summary']}")
                if item.get("source_url"):
                    st.markdown(f"[Open source]({item['source_url']})")
        with st.form(f"evidence-{assessment['id']}"):
            title = st.text_input("Evidence title")
            summary = st.text_area("Evidence summary")
            url = st.text_input("Source URL (optional)")
            if st.form_submit_button("Add evidence"):
                call("POST", f"/assessments/{assessment['id']}/evidence", body={"title": title, "summary": summary, "source_url": url or None}, success="Evidence added.")
                st.rerun()


def employee_pages(user: dict) -> None:
    page = st.sidebar.radio("Workspace", ["Overview", "My assessments", "Submit self-assessment"])
    if page == "Submit self-assessment":
        st.header("Self-assessment")
        assessment_form("self")
    elif page == "My assessments":
        st.header("My assessments")
        assessment_table(load("/assessments") or [])
    else:
        st.header(f"Welcome, {user['full_name']}")
        periods = load("/evaluation-periods") or []
        active = [p for p in periods if p["is_active"]]
        a, b = st.columns(2)
        a.metric("Active evaluation periods", len(active))
        assessments = load("/assessments") or []
        b.metric("Submitted assessments", len(assessments))
        if active:
            st.info("An evaluation period is active. Complete your self-assessment from the navigation menu.")


def supervisor_pages(user: dict) -> None:
    page = st.sidebar.radio("Workspace", ["Team overview", "Assessments", "Assess a direct report", "My self-assessment", "Score calculator"])
    if page == "My self-assessment":
        st.header("My self-assessment")
        assessment_form("self")
    elif page in ("Assess a direct report", "Team overview"):
        team = [e for e in (load("/employees") or []) if e.get("supervisor_id") == user.get("employee_id")]
        if page == "Team overview":
            st.header("Team overview")
            st.metric("Direct reports", len(team))
            if team:
                st.dataframe([{"Name": e["full_name"], "Employee number": e["employee_number"], "Role": e["designation"], "Department": e["department_id"]} for e in team], use_container_width=True, hide_index=True)
            st.caption("The employee directory endpoint returns the organization directory; assessment permissions are enforced for your direct reports.")
        else:
            st.header("Assess a direct report")
            if not team:
                st.info("No employee records are available.")
            else:
                labels, mapping = options(team, lambda e: f"{e['full_name']} · {e['employee_number']}")
                selected = st.selectbox("Employee", labels)
                assessment_form("supervisor", mapping[selected]["id"])
    elif page == "Score calculator":
        score_calculator()
    else:
        st.header("Team assessments")
        assessment_table(load("/assessments") or [])


def organization_admin() -> None:
    st.subheader("Departments")
    with st.form("department-create"):
        name = st.text_input("Department name")
        if st.form_submit_button("Add department"):
            call("POST", "/departments", body={"name": name}, success="Department created.")
            st.rerun()
    depts = load("/departments") or []
    st.dataframe(depts, use_container_width=True, hide_index=True)
    st.subheader("Employee directory")
    dept_labels, dept_map = options(depts, lambda d: d["name"])
    with st.form("employee-create"):
        number = st.text_input("Employee number")
        full_name = st.text_input("Full name")
        designation = st.text_input("Job title")
        department = st.selectbox("Department", dept_labels) if dept_labels else None
        employees = load("/employees") or []
        sup_labels, sup_map = options(employees, lambda e: f"{e['full_name']} · {e['employee_number']}")
        supervisor = st.selectbox("Supervisor (optional)", ["None", *sup_labels])
        if st.form_submit_button("Add employee", disabled=not dept_labels):
            body = {"employee_number": number, "full_name": full_name, "designation": designation, "department_id": dept_map[department]["id"], "supervisor_id": sup_map[supervisor]["id"] if supervisor != "None" else None}
            call("POST", "/employees", body=body, success="Employee created.")
            st.rerun()
    st.dataframe([{"Name": e["full_name"], "Number": e["employee_number"], "Title": e["designation"], "Department": e["department_id"], "Supervisor": e["supervisor_id"], "Active": e["is_active"]} for e in (load("/employees") or [])], use_container_width=True, hide_index=True)


def configuration_admin() -> None:
    left, right = st.columns(2)
    with left:
        st.subheader("KPIs")
        with st.form("kpi-create"):
            code = st.text_input("KPI code", help="Letters, numbers, underscores, and hyphens")
            name = st.text_input("KPI name")
            description = st.text_area("Description")
            weight = st.number_input("Default weight (%)", min_value=0.0, max_value=100.0, step=1.0)
            if st.form_submit_button("Add KPI"):
                call("POST", "/kpis", body={"code": code, "name": name, "description": description, "default_weight": weight}, success="KPI created.")
                st.rerun()
        st.dataframe([{"Code": k["code"], "Name": k["name"], "Weight": k["default_weight"], "Active": k["is_active"]} for k in (load("/kpis", params={"include_inactive": True}) or [])], use_container_width=True, hide_index=True)
    with right:
        st.subheader("Evaluation periods")
        with st.form("period-create"):
            name = st.text_input("Period name", placeholder="2026-Q4")
            start = st.date_input("Start date", value=date.today())
            end = st.date_input("End date", value=date.today())
            if st.form_submit_button("Add period"):
                call("POST", "/evaluation-periods", body={"name": name, "start_date": start.isoformat(), "end_date": end.isoformat()}, success="Evaluation period created.")
                st.rerun()
        st.dataframe([{"Name": p["name"], "Start": p["start_date"], "End": p["end_date"], "Active": p["is_active"]} for p in (load("/evaluation-periods", params={"include_inactive": True}) or [])], use_container_width=True, hide_index=True)


def user_admin() -> None:
    st.subheader("Existing accounts")
    users = load("/auth/users") or []
    if users:
        st.caption(f"{len(users)} account(s)")
        st.dataframe(
            [
                {
                    "Name": account["full_name"],
                    "Email": account["email"],
                    "Role": ROLE_LABELS.get(account["role"], account["role"]),
                    "Employee link": account["employee_id"] or "—",
                    "Active": account["is_active"],
                }
                for account in users
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No accounts found.")

    st.subheader("Create account")
    employees = load("/employees") or []
    emp_labels, emp_map = options(employees, lambda e: f"{e['full_name']} · {e['employee_number']}")
    with st.form("user-create"):
        email = st.text_input("Email")
        name = st.text_input("Full name")
        password = st.text_input("Temporary password", type="password", help="At least 12 characters")
        role = st.selectbox("Role", ["admin", "hr", "supervisor", "employee"])
        employee = st.selectbox("Linked employee record", ["Select employee", *emp_labels]) if role in ("employee", "supervisor") else None
        if st.form_submit_button("Create account"):
            body = {"email": email, "full_name": name, "password": password, "role": role}
            if role in ("employee", "supervisor") and employee != "Select employee":
                body["employee_id"] = emp_map[employee]["id"]
            call("POST", "/auth/users", body=body, success="Account created.")


def rules_page() -> None:
    st.header("Recommendation rules")
    st.caption("Rules match supervisor scores, KPI gaps, and (when available) self/supervisor disagreement.")
    with st.expander("Create rule"):
        with st.form("rule-create"):
            name = st.text_input("Rule name")
            category = st.text_input("Category", value="development")
            priority = st.selectbox("Priority", ["low", "medium", "high"])
            action = st.text_area("Recommended action")
            explanation = st.text_input("Explanation template", value="For {employee_name} in {period_name}: overall score {overall_score}; KPI gaps: {gap_kpis}.")
            score_below = st.number_input("Match when score is below (optional; 0 disables)", min_value=0.0, max_value=100.0, value=0.0)
            score_at_least = st.number_input("Match when score is at least (optional; 0 disables)", min_value=0.0, max_value=100.0, value=0.0)
            disagreement = st.number_input("Match disagreement at least (optional; 0 disables)", min_value=0.0, max_value=100.0, value=0.0)
            kpis = load("/kpis") or []
            gap_codes = st.multiselect("Match any of these KPI gaps", [k["code"] for k in kpis])
            if st.form_submit_button("Create rule"):
                conditions = {}
                if score_below > 0: conditions["overall_score_below"] = score_below
                if score_at_least > 0: conditions["overall_score_at_least"] = score_at_least
                if disagreement > 0: conditions["disagreement_at_least"] = disagreement
                if gap_codes: conditions["gap_kpi_codes"] = gap_codes
                call("POST", "/recommendation-rules", body={"name": name, "category": category, "priority": priority, "conditions": conditions, "action": action, "explanation_template": explanation}, success="Rule created.")
                st.rerun()
    rules = load("/recommendation-rules", params={"include_inactive": True}) or []
    if rules:
        st.dataframe([{"Name": r["name"], "Category": r["category"], "Priority": r["priority"], "Conditions": json.dumps(r["conditions"]), "Action": r["action"], "Active": r["is_active"]} for r in rules], use_container_width=True, hide_index=True)
        active = [r for r in rules if r["is_active"]]
        if active:
            labels, mapping = options(active, lambda r: r["name"])
            selected = st.selectbox("Deactivate rule", labels)
            if st.button("Deactivate selected rule"):
                call("PATCH", f"/recommendation-rules/{mapping[selected]['id']}/deactivate", success="Rule deactivated.")
                st.rerun()
    else:
        st.info("No recommendation rules configured.")


def reviews_page() -> None:
    st.header("Recommendations and HR review")
    employees = load("/employees") or []
    periods = load("/evaluation-periods") or []
    if employees and periods:
        e_labels, e_map = options(employees, lambda e: f"{e['full_name']} · {e['employee_number']}")
        p_labels, p_map = options(periods, lambda p: p["name"])
        with st.form("generate-recommendations"):
            employee = st.selectbox("Employee", e_labels)
            period = st.selectbox("Evaluation period", p_labels)
            if st.form_submit_button("Generate recommendations", type="primary"):
                call("POST", f"/employees/{e_map[employee]['id']}/periods/{p_map[period]['id']}/recommendations", success="Recommendations generated.")
                st.rerun()


def score_calculator() -> None:
    st.header("Weighted score calculator")
    st.caption("Calculate a score from KPI results. Weights must total exactly 100%.")
    kpis = load("/kpis") or []
    if not kpis:
        st.info("Create active KPIs before calculating a score.")
        return
    periods = load("/evaluation-periods") or []
    with st.form("score-calculator"):
        employee_id = st.text_input("Employee ID", value="DEMO-001", help="Required by the score calculator API.")
        period = st.text_input("Evaluation period name", value=periods[0]["name"] if periods else "")
        scores = []
        for kpi in kpis:
            a, b = st.columns(2)
            score = a.number_input(f"{kpi['name']} score", min_value=0.0, max_value=100.0, value=70.0, key=f"calc-score-{kpi['id']}")
            weight = b.number_input(f"{kpi['name']} weight (%)", min_value=0.0, max_value=100.0, value=float(kpi["default_weight"]), key=f"calc-weight-{kpi['id']}")
            scores.append({"kpi_code": kpi["code"], "score": score, "weight": weight})
        if st.form_submit_button("Calculate score", type="primary"):
            if not employee_id.strip():
                st.error("Enter an employee ID to calculate this score.")
                return
            result = call("POST", "/performance/evaluate", body={"employee_id": employee_id, "evaluation_period": period, "scores": scores}, success="Score calculated.")
            if result:
                st.metric("Overall score", result["overall_score"])
                st.write(f"Classification: **{result['classification'].replace('_', ' ').title()}**")
                st.write("KPI gaps: " + (", ".join(result["gaps"]) if result["gaps"] else "None"))
    items = load("/recommendations") or []
    if not items:
        st.info("No recommendations yet. Generate them after a supervisor assessment has been submitted.")
        return
    st.dataframe([{"Category": x["category"], "Priority": x["priority"], "Action": x["action"], "Explanation": x["explanation"], "Status": x["review_status"], "Employee": x["employee_id"], "Period": x["period_id"]} for x in items], use_container_width=True, hide_index=True)
    pending = [x for x in items if x["review_status"] == "pending"]
    if pending:
        labels, mapping = options(pending, lambda x: f"{x['category']} · {x['priority']} · {x['id'][:8]}")
        selected = st.selectbox("Review recommendation", labels)
        note = st.text_area("Review note")
        yes, no = st.columns(2)
        for col, status in ((yes, "approved"), (no, "rejected")):
            if col.button(status.title(), use_container_width=True):
                call("PATCH", f"/recommendations/{mapping[selected]['id']}/review", body={"status": status, "note": note}, success=f"Recommendation {status}.")
                st.rerun()


def reporting_page() -> None:
    st.header("Reporting and audit")
    periods = load("/evaluation-periods") or []
    if periods:
        labels, mapping = options(periods, lambda p: p["name"])
        period_name = st.selectbox("Evaluation period", labels)
        period = mapping[period_name]
        summary = load(f"/dashboard/periods/{period['id']}")
        if summary:
            st.subheader("Period dashboard")
            scalar = {k: v for k, v in summary.items() if isinstance(v, (str, int, float, bool)) or v is None}
            cols = st.columns(max(1, min(len(scalar), 4)))
            for i, (key, value) in enumerate(scalar.items()):
                cols[i % len(cols)].metric(key.replace("_", " ").title(), value if value is not None else "—")
            details = {k: v for k, v in summary.items() if isinstance(v, (list, dict))}
            if details:
                with st.expander("Breakdown"):
                    st.json(details)
        try:
            csv_bytes = api("GET", f"/reports/periods/{period['id']}.csv")
            st.download_button("Download period CSV", csv_bytes, file_name=f"{period['name']}-report.csv", mime="text/csv")
        except APIError as exc:
            st.error(str(exc))
    st.subheader("Audit history")
    events = load("/audit-events") or []
    if events:
        st.dataframe([{"Time": x["created_at"], "Action": x["action"], "Resource": x["resource_type"], "Resource ID": x["resource_id"], "Actor": x["actor_id"], "Details": json.dumps(x["details"])} for x in events], use_container_width=True, hide_index=True)
    else:
        st.info("No audit events found.")


def hr_pages(admin: bool) -> None:
    choices = ["Overview", "Organization", "KPIs and periods", "Assessments", "Score calculator", "Recommendations", "Rules", "Reports and audit"]
    if admin:
        choices.insert(2, "User accounts")
    page = st.sidebar.radio("Workspace", choices)
    if page == "Overview":
        st.header("HR workspace" if not admin else "Administrator workspace")
        periods = load("/evaluation-periods") or []
        employees = load("/employees") or []
        recommendations = load("/recommendations") or []
        a, b, c = st.columns(3)
        a.metric("Employees", len(employees))
        b.metric("Active periods", sum(bool(p["is_active"]) for p in periods))
        c.metric("Pending recommendations", sum(x["review_status"] == "pending" for x in recommendations))
        st.info("Use the workspace menu to manage evaluations, review recommendations, and download reports.")
    elif page == "Organization":
        st.header("Organization management")
        organization_admin()
    elif page == "User accounts":
        st.header("Account management")
        user_admin()
    elif page == "KPIs and periods":
        st.header("Performance configuration")
        configuration_admin()
    elif page == "Assessments":
        st.header("Assessment submissions")
        assessment_table(load("/assessments") or [])
    elif page == "Score calculator":
        score_calculator()
    elif page == "Recommendations":
        reviews_page()
    elif page == "Rules":
        rules_page()
    else:
        reporting_page()


def main() -> None:
    user = st.session_state.get("user")
    if not user:
        login_screen()
        return
    with st.sidebar:
        st.title("📊 Performance")
        st.caption(f"{user['full_name']} · {ROLE_LABELS.get(user['role'], user['role'])}")
        st.caption(f"Connected to {API_URL}")
        if st.button("Sign out", use_container_width=True):
            st.session_state.clear()
            st.rerun()
    role = user["role"]
    if role == "employee":
        employee_pages(user)
    elif role == "supervisor":
        supervisor_pages(user)
    elif role in ("admin", "hr"):
        hr_pages(role == "admin")
    else:
        st.error("Your account has an unsupported role.")


if "user" in st.session_state and "token" in st.session_state:
    try:
        st.session_state.user = api("GET", "/auth/me")
    except APIError:
        st.session_state.clear()

main()
