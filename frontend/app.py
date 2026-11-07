import streamlit as st


st.set_page_config(page_title="Employee Performance System", page_icon="📊", layout="wide")

st.title("Employee Performance System")
st.caption("Progressive performance evaluation with explainable HR recommendations")

st.info("The frontend foundation is ready. Role-specific dashboards will be added in the next milestone.")

with st.sidebar:
    st.header("Navigation")
    st.selectbox("Role", ["Employee", "Supervisor", "HR Personnel", "Administrator"])

st.subheader("MVP modules")
st.write("Authentication, employee management, KPI configuration, evaluations, recommendations, reporting, and audit history.")
