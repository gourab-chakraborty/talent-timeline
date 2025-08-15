"""
Talent Timeline — Full MVP single-file Streamlit app

Features:
- SQLite-backed users with hashed passwords (register/login)
- Candidate profiles: basic info (name, email, location), availability, profile text
- Timeline events: title, company/project, start_date, end_date, skills (comma separated)
- Recruiter search: skills, min years, availability, location
- Candidate & Recruiter dashboards: timeline visualization, skill summary
- Export matched candidates as CSV (for outreach)

Run:
    pip install -r requirements.txt
    streamlit run app.py
"""

import streamlit as st
import sqlite3
import hashlib
from datetime import datetime, date
import pandas as pd
import plotly.express as px
from dateutil import parser
import io

DB_FILE = "talent_timeline.db"

# -------------------------
# Database helpers
# -------------------------
def get_conn():
    return sqlite3.connect(DB_FILE, check_same_thread=False)

def init_db():
    conn = get_conn()
    c = conn.cursor()
    # users: username (pk), password_hash, role (Candidate/Recruiter), created_at
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL,
        created_at TEXT
    )
    """)
    # candidate profiles: candidate_id (username FK), full_name, email, location, availability, profile_text, created_at
    c.execute("""
    CREATE TABLE IF NOT EXISTS candidates (
        candidate_id TEXT PRIMARY KEY,
        full_name TEXT,
        email TEXT,
        location TEXT,
        availability TEXT,
        profile_text TEXT,
        created_at TEXT,
        FOREIGN KEY(candidate_id) REFERENCES users(username)
    )
    """)
    # timeline events: id, candidate_id, title, company, start_date, end_date, skills (csv)
    c.execute("""
    CREATE TABLE IF NOT EXISTS timeline_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        candidate_id TEXT,
        title TEXT,
        company TEXT,
        start_date TEXT,
        end_date TEXT,
        skills TEXT,
        created_at TEXT,
        FOREIGN KEY(candidate_id) REFERENCES candidates(candidate_id)
    )
    """)
    conn.commit()
    conn.close()

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def add_user(username: str, password: str, role: str) -> bool:
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username,password_hash,role,created_at) VALUES (?,?,?,?)",
                  (username, hash_password(password), role, datetime.utcnow().isoformat()))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False

def verify_user(username: str, password: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT role FROM users WHERE username = ? AND password_hash = ?", (username, hash_password(password)))
    r = c.fetchone()
    conn.close()
    return r[0] if r else None

def create_candidate_profile(username: str, full_name: str, email: str, location: str, availability: str, profile_text: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
    INSERT OR REPLACE INTO candidates (candidate_id, full_name, email, location, availability, profile_text, created_at)
    VALUES (?,?,?,?,?,?,?)
    """, (username, full_name, email, location, availability, profile_text, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()

def get_candidate_profile(candidate_id: str):
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM candidates WHERE candidate_id = ?", conn, params=(candidate_id,))
    conn.close()
    if df.empty:
        return None
    return df.iloc[0].to_dict()

def add_timeline_event(candidate_id: str, title: str, company: str, start_date: str, end_date: str, skills: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
    INSERT INTO timeline_events (candidate_id, title, company, start_date, end_date, skills, created_at)
    VALUES (?,?,?,?,?,?,?)
    """, (candidate_id, title, company, start_date, end_date, skills, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()

def get_timeline(candidate_id: str):
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM timeline_events WHERE candidate_id = ? ORDER BY start_date DESC", conn, params=(candidate_id,))
    conn.close()
    return df

def search_candidates(skills=None, min_years=None, availability=None, location=None):
    """
    skills: list of skill strings (lowercased)
    min_years: float
    availability: one of "Any","Immediate","1 month","3 months"
    location: string or None
    """
    conn = get_conn()
    cand_df = pd.read_sql_query("SELECT * FROM candidates", conn)
    # If there are no candidate profiles, return empty df
    if cand_df.empty:
        conn.close()
        return pd.DataFrame()
    results = []
    for _, row in cand_df.iterrows():
        cid = row['candidate_id']
        tdf = pd.read_sql_query("SELECT * FROM timeline_events WHERE candidate_id = ?", conn, params=(cid,))
        # compute years experience
        total_days = 0
        for _, ev in tdf.iterrows():
            s = ev['start_date']
            e = ev['end_date'] if ev['end_date'] and str(ev['end_date']).lower()!='none' else date.today().isoformat()
            try:
                s_dt = parser.parse(s).date()
            except:
                s_dt = date.today()
            try:
                e_dt = parser.parse(e).date()
            except:
                e_dt = date.today()
            total_days += max(0, (e_dt - s_dt).days)
        years = total_days / 365.0
        # skill matching
        skill_match_count = 0
        total_req = len(skills) if skills else 0
        if skills and total_req>0:
            # check each required skill against events' skills
            for sk in skills:
                found = False
                for _, ev in tdf.iterrows():
                    ev_sk = (ev['skills'] or "")
                    ev_list = [x.strip().lower() for x in ev_sk.split(",") if x.strip()]
                    if sk.strip().lower() in ev_list:
                        found = True
                        break
                if found:
                    skill_match_count += 1
            if skill_match_count < total_req:
                # not enough skills matched; skip candidate
                continue
        # availability filter
        avail_ok = True
        if availability and availability != "Any":
            avail_ok = (str(row.get('availability','')).lower().startswith(availability.lower()))
        # location filter
        loc_ok = True
        if location and str(location).strip()!="":
            loc_ok = (str(row.get('location','')).strip().lower() in str(row.get('location','')).strip().lower()) or (str(location).strip().lower() in str(row.get('location','')).strip().lower())
        if not avail_ok or not loc_ok:
            continue
        match_score = 0.0
        if total_req>0:
            match_score = skill_match_count / total_req
        else:
            match_score = min(1.0, years/5.0)  # loose score if no skills specified
        results.append({
            "candidate_id": cid,
            "full_name": row.get('full_name'),
            "email": row.get('email'),
            "location": row.get('location'),
            "availability": row.get('availability'),
            "years_experience": round(years,2),
            "profile_text": row.get('profile_text'),
            "match_score": round(match_score,2)
        })
    conn.close()
    df_res = pd.DataFrame(results).sort_values(by="match_score", ascending=False)
    return df_res

def export_candidates_csv(df: pd.DataFrame):
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode()

# -------------------------
# Utility visual helpers
# -------------------------
def timeline_plot_df(tdf, candidate_name):
    if tdf.empty:
        return None
    df = tdf.copy()
    df['start'] = pd.to_datetime(df['start_date'])
    df['end'] = df['end_date'].apply(lambda x: pd.to_datetime(x) if x and str(x).lower()!='none' else pd.to_datetime(date.today().isoformat()))
    fig = px.timeline(df, x_start="start", x_end="end", y="company", color="title", hover_data=["skills"])
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(height=350, margin=dict(l=20,r=20,t=30,b=20), title=f"Career timeline — {candidate_name}")
    return fig

def skills_summary_df(tdf):
    skills = {}
    for _, ev in tdf.iterrows():
        sks = (ev['skills'] or "")
        if not isinstance(sks, str): 
            continue
        for s in [x.strip().lower() for x in sks.split(",") if x.strip()]:
            skills[s] = skills.get(s,0)+1
    if not skills:
        return pd.DataFrame()
    s_df = pd.DataFrame([{"skill":k,"count":v} for k,v in skills.items()]).sort_values("count", ascending=False)
    return s_df

# -------------------------
# Seed demo data (only if empty)
# -------------------------
def seed_demo_data():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT count(1) FROM users")
    users_count = c.fetchone()[0]
    if users_count == 0:
        add_user("recruiter", "recruiter123", "Recruiter")
        add_user("candidate", "candidate123", "Candidate")
    c.execute("SELECT count(1) FROM candidates")
    cnt = c.fetchone()[0]
    if cnt == 0:
        # create some demo candidate profiles and timeline events
        create_candidate_profile("candidate", "Ananya Gupta", "ananya@example.com", "Bengaluru", "1 month", "Senior ML Engineer — built data platforms and ML services")
        add_timeline_event("candidate", "ML Engineer", "Customer360", "2021-01-01", "2023-06-30", "python,pytorch,pandas,nlp,aws")
        add_timeline_event("candidate", "Data Engineer", "DataCorp", "2019-01-01", "2020-12-31", "python,spark,sql")

        add_user("rahul", "rahul123", "Candidate")
        create_candidate_profile("rahul", "Rahul Mehta", "rahul@example.com", "Hyderabad", "Immediate", "Full-stack dev — React/Node/Kubernetes")
        add_timeline_event("rahul", "Senior Engineer", "ShopX", "2022-01-01", None, "react,node,aws,kubernetes")
        add_timeline_event("rahul", "Engineer", "WebStart", "2019-06-01", "2021-12-31", "javascript,react")

        add_user("meera", "meera123", "Candidate")
        create_candidate_profile("meera", "Meera Shah", "meera@example.com", "Mumbai", "1 month", "Data engineer with streaming experience")
        add_timeline_event("meera", "Data Engineer", "StreamWorks", "2021-08-01", None, "python,spark,kafka")
        add_timeline_event("meera", "Analyst", "RetailCo", "2017-09-01", "2020-12-31", "sql,etl")
    conn.close()

# -------------------------
# Streamlit App UI
# -------------------------
def main():
    st.set_page_config(page_title="Talent Timeline", layout="wide")
    init_db()
    seed_demo_data()

    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
        st.session_state.username = None
        st.session_state.role = None

    st.title("Talent Timeline — Career Journey & Skills (MVP)")

    # top nav
    menu = ["Home","About"]
    if not st.session_state.logged_in:
        menu += ["Login","Register"]
    else:
        menu += ["Dashboard","Logout"]

    choice = st.sidebar.selectbox("Menu", menu)

    if choice == "Home":
        st.markdown("**Find candidates quickly with a visual career timeline and skill summary.**")
        st.info("This is a demo MVP. Use Register to create Candidate or Recruiter accounts (or use demo accounts).")
        st.markdown("**Demo credentials**: recruiter / recruiter123  |  candidate / candidate123  |  rahul / rahul123  |  meera / meera123")

    elif choice == "About":
        st.header("About Talent Timeline")
        st.write("A recruiter-first interface showing career journey, skills and availability.")
        st.write("Built for demos & early validation. Not for production without customization (auth, SSO, secure hosting).")

    elif choice == "Register":
        st.header("Register")
        with st.form("register_form", clear_on_submit=True):
            username = st.text_input("Choose a username")
            password = st.text_input("Choose a password", type="password")
            role = st.selectbox("Role", ["Candidate","Recruiter"])
            submit = st.form_submit_button("Register")
            if submit:
                ok = add_user(username, password, role)
                if ok:
                    st.success("Account created. Please Login.")
                    # if candidate, create empty candidate profile row
                    if role == "Candidate":
                        create_candidate_profile(username, "", "", "", "Not open", "")
                else:
                    st.error("Username already exists. Pick another one.")

    elif choice == "Login":
        st.header("Login")
        with st.form("login_form", clear_on_submit=False):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submit = st.form_submit_button("Login")
            if submit:
                role = verify_user(username, password)
                if role:
                    st.session_state.logged_in = True
                    st.session_state.username = username
                    st.session_state.role = role
                    st.success(f"Welcome {username} ({role})")
                else:
                    st.error("Invalid credentials. Use demo credentials if you just want to test quickly.")

    elif choice == "Logout":
        st.session_state.logged_in = False
        st.session_state.username = None
        st.session_state.role = None
        st.success("Logged out")

    elif choice == "Dashboard":
        if not st.session_state.logged_in:
            st.warning("Please login first.")
            return
        role = st.session_state.role
        username = st.session_state.username

        if role == "Candidate":
            st.header("Candidate Dashboard")
            st.subheader("Profile")
            prof = get_candidate_profile(username) or {}
            col1, col2 = st.columns([2,1])
            with col1:
                full_name = st.text_input("Full name", prof.get("full_name",""))
                email = st.text_input("Email", prof.get("email",""))
                location = st.text_input("Location", prof.get("location",""))
                availability = st.selectbox("Availability", ["Immediate","1 month","3 months","Not open"], index=(["Immediate","1 month","3 months","Not open"].index(prof.get("availability","Not open")) if prof.get("availability") else 3))
                profile_text = st.text_area("Profile summary", prof.get("profile_text",""))
                if st.button("Save profile"):
                    create_candidate_profile(username, full_name, email, location, availability, profile_text)
                    st.success("Profile saved.")
            with col2:
                st.write("Actions")
                if st.button("Add timeline event"):
                    st.info("Use the 'Add Timeline Event' accordion below")

            st.markdown("---")
            st.subheader("Add timeline event")
            with st.form("add_event"):
                title = st.text_input("Role / Title", "")
                company = st.text_input("Company / Project", "")
                start_date = st.date_input("Start date", value=date(2020,1,1))
                end_option = st.selectbox("End date or Current", ["Current","Specific date"])
                if end_option == "Specific date":
                    end_date = st.date_input("End date", value=date.today())
                    end_val = end_date.isoformat()
                else:
                    end_val = None
                skills = st.text_input("Skills used (comma-separated)", "")
                submit = st.form_submit_button("Add Event")
                if submit:
                    add_timeline_event(username, title, company, start_date.isoformat(), end_val, skills)
                    st.success("Timeline event added.")

            st.markdown("---")
            st.subheader("Your timeline")
            tdf = get_timeline(username)
            if tdf.empty:
                st.info("No timeline events yet. Use the form above to add your projects/roles.")
            else:
                st.plotly_chart(timeline_plot_df(tdf, prof.get("full_name", username)), use_container_width=True)
                ssum = skills_summary_df(tdf)
                if not ssum.empty:
                    st.write("Skills summary (frequency in timeline)")
                    st.table(ssum)

        elif role == "Recruiter":
            st.header("Recruiter Dashboard")
            st.subheader("Search candidates")
            col1, col2, col3 = st.columns(3)
            with col1:
                skill_q = st.text_input("Skills (comma-separated)", "python,aws")
            with col2:
                min_years = st.number_input("Min Years Experience (approx)", min_value=0.0, max_value=50.0, value=2.0, step=0.5)
            with col3:
                availability = st.selectbox("Availability", ["Any","Immediate","1 month","3 months"], index=0)
            location = st.text_input("Location (optional)", "")
            if st.button("Search"):
                skills = [s.strip().lower() for s in skill_q.split(",") if s.strip()]
                df = search_candidates(skills=skills if skills else None, min_years=min_years, availability=availability, location=location)
                if df.empty:
                    st.warni
