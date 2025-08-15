"""
TalentGraph Copilot — Full MVP (single-file)
Features:
- SQLite-backed auth (register/login)
- Candidate: education, projects, current employer, notice period days
- Recruiter: upload jobs (CSV or form), search by tech, last-used timeframe, responsibilities
- Export matched candidates CSV
- Demo data seeded on first run
"""

import streamlit as st
import sqlite3
import hashlib
from datetime import datetime, date
import pandas as pd
import plotly.express as px
from dateutil import parser, relativedelta
import io

DB = "talentgraph_full.db"

# ---------- DB helpers ----------
def get_conn():
    return sqlite3.connect(DB, check_same_thread=False)

def init_db():
    conn = get_conn()
    c = conn.cursor()
    # users
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL,
        created_at TEXT
    )""")
    # candidate basic profile
    c.execute("""
    CREATE TABLE IF NOT EXISTS candidates (
        username TEXT PRIMARY KEY,
        full_name TEXT,
        email TEXT,
        location TEXT,
        current_employer TEXT,
        notice_given_date TEXT,   -- ISO date when notice was given
        availability TEXT,        -- Immediate/1 month/3 months/Not open
        summary TEXT,
        created_at TEXT,
        FOREIGN KEY(username) REFERENCES users(username)
    )""")
    # education
    c.execute("""
    CREATE TABLE IF NOT EXISTS education (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        institution TEXT,
        degree TEXT,
        start_date TEXT,
        end_date TEXT,
        notes TEXT,
        FOREIGN KEY(username) REFERENCES users(username)
    )""")
    # projects
    c.execute("""
    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        project_name TEXT,
        client TEXT,
        role TEXT,
        responsibilities TEXT,
        description TEXT,
        tech_stack TEXT,    -- comma-separated
        start_date TEXT,
        end_date TEXT,
        FOREIGN KEY(username) REFERENCES users(username)
    )""")
    # jobs uploaded by recruiters
    c.execute("""
    CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        recruiter TEXT,
        title TEXT,
        skills TEXT,
        description TEXT,
        created_at TEXT
    )""")
    conn.commit()
    conn.close()

def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

# user management
def create_user(username, password, role):
    conn = get_conn(); c = conn.cursor()
    try:
        c.execute("INSERT INTO users(username,password_hash,role,created_at) VALUES (?,?,?,?)",
                  (username, hash_password(password), role, datetime.utcnow().isoformat()))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False

def verify_user(username, password):
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT role FROM users WHERE username=? AND password_hash=?", (username, hash_password(password)))
    r = c.fetchone(); conn.close()
    return r[0] if r else None

# candidate functions
def upsert_candidate_profile(username, full_name, email, location, current_employer, notice_given_date, availability, summary):
    conn = get_conn(); c = conn.cursor()
    c.execute("""
    INSERT INTO candidates(username,full_name,email,location,current_employer,notice_given_date,availability,summary,created_at)
    VALUES (?,?,?,?,?,?,?,?,?)
    ON CONFLICT(username) DO UPDATE SET
      full_name=excluded.full_name,
      email=excluded.email,
      location=excluded.location,
      current_employer=excluded.current_employer,
      notice_given_date=excluded.notice_given_date,
      availability=excluded.availability,
      summary=excluded.summary
    """, (username, full_name, email, location, current_employer, notice_given_date, availability, summary, datetime.utcnow().isoformat()))
    conn.commit(); conn.close()

def add_education(username, institution, degree, start_date, end_date, notes):
    conn = get_conn(); c = conn.cursor()
    c.execute("INSERT INTO education(username,institution,degree,start_date,end_date,notes) VALUES (?,?,?,?,?,?)",
              (username,institution,degree,start_date,end_date,notes))
    conn.commit(); conn.close()

def get_education(username):
    conn = get_conn(); df = pd.read_sql_query("SELECT * FROM education WHERE username=? ORDER BY start_date DESC", conn, params=(username,))
    conn.close(); return df

def add_project(username, project_name, client, role, responsibilities, description, tech_stack, start_date, end_date):
    conn = get_conn(); c = conn.cursor()
    c.execute("""INSERT INTO projects(username,project_name,client,role,responsibilities,description,tech_stack,start_date,end_date)
                 VALUES (?,?,?,?,?,?,?,?,?)""", (username,project_name,client,role,responsibilities,description,tech_stack,start_date,end_date))
    conn.commit(); conn.close()

def get_projects(username):
    conn = get_conn(); df = pd.read_sql_query("SELECT * FROM projects WHERE username=? ORDER BY start_date DESC", conn, params=(username,))
    conn.close(); return df

def add_job(recruiter, title, skills, description):
    conn = get_conn(); c = conn.cursor()
    c.execute("INSERT INTO jobs(recruiter,title,skills,description,created_at) VALUES (?,?,?,?,?)",
              (recruiter,title,skills,description,datetime.utcnow().isoformat()))
    conn.commit(); conn.close()

def get_jobs_for_recruiter(recruiter):
    conn = get_conn(); df = pd.read_sql_query("SELECT * FROM jobs WHERE recruiter=? ORDER BY created_at DESC", conn, params=(recruiter,))
    conn.close(); return df

# search logic
def search_candidates(techs=None, last_used_months=None, responsibilities_keyword=None, availability=None, location=None):
    """
    techs: list of tech strings (lowercased)
    last_used_months: int (e.g., 12 means used within last 12 months)
    responsibilities_keyword: substring to match in responsibilities
    """
    conn = get_conn()
    # get all candidates with profiles
    cand_df = pd.read_sql_query("SELECT * FROM candidates", conn)
    results = []
    for _, row in cand_df.iterrows():
        username = row['username']
        # check availability filter
        if availability and availability != "Any":
            if not row['availability'] or not str(row['availability']).lower().startswith(availability.lower()):
                continue
        if location and location.strip():
            if not row['location'] or location.strip().lower() not in str(row['location']).lower():
                continue
        # projects for candidate
        proj_df = pd.read_sql_query("SELECT * FROM projects WHERE username=?", conn, params=(username,))
        # compute years experience roughly
        total_days = 0
        used_recent = False
        match_techs = 0
        total_req = len(techs) if techs else 0
        for _, p in proj_df.iterrows():
            s = p['start_date']
            e = p['end_date'] if p['end_date'] and str(p['end_date']).lower()!='none' else date.today().isoformat()
            try:
                s_dt = parser.parse(s).date()
            except:
                s_dt = date.today()
            try:
                e_dt = parser.parse(e).date()
            except:
                e_dt = date.today()
            total_days += max(0, (e_dt - s_dt).days)
            # responsibilities keyword
            if responsibilities_keyword and responsibilities_keyword.strip():
                if responsibilities_keyword.strip().lower() not in str(p.get('responsibilities','')).lower() and responsibilities_keyword.strip().lower() not in str(p.get('description','')).lower():
                    pass
                else:
                    # ok, this project satisfies responsibilities search
                    pass
            # tech matches
            if techs:
                p_techs = [t.strip().lower() for t in (p.get('tech_stack') or "").split(",") if t.strip()]
                for t in techs:
                    if t.lower() in p_techs:
                        match_techs += 1
                # last used check
                if last_used_months:
                    # if end_date within last X months, mark used_recent True if tech present
                    try:
                        end_dt = parser.parse(p['end_date']).date() if p['end_date'] else date.today()
                    except:
                        end_dt = date.today()
                    months_diff = (date.today().year - end_dt.year) * 12 + (date.today().month - end_dt.month)
                    if months_diff <= last_used_months:
                        # if tech present in this project
                        for t in techs:
                            if t.lower() in p_techs:
                                used_recent = True
            else:
                # if no techs requested, still check last_used if provided (irrelevant)
                pass
        # skill match acceptance rules
        if techs and total_req > 0:
            # require at least one tech match in projects
            if match_techs == 0:
                continue
            if last_used_months and not used_recent:
                # require at least one of the techs used recently
                continue
        # responsibilities keyword filter across projects
        if responsibilities_keyword and responsibilities_keyword.strip():
            found_resp = False
            for _, p in proj_df.iterrows():
                if responsibilities_keyword.strip().lower() in str(p.get('responsibilities','')).lower() or responsibilities_keyword.strip().lower() in str(p.get('description','')).lower():
                    found_resp = True
                    break
            if not found_resp:
                continue
        # passed filters -> compute match_score (simple)
        years = total_days / 365.0
        match_score = 0.0
        if total_req > 0:
            match_score = min(1.0, match_techs / total_req)
        else:
            match_score = min(1.0, years/5.0)
        results.append({
            "username": username,
            "full_name": row.get('full_name'),
            "email": row.get('email'),
            "location": row.get('location'),
            "availability": row.get('availability'),
            "years_experience": round(years,2),
            "match_score": round(match_score,2)
        })
    conn.close()
    df = pd.DataFrame(results).sort_values(by="match_score", ascending=False)
    return df

def export_df_csv_bytes(df):
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode()

# ---------- seed demo data ----------
def seed_demo():
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT count(1) FROM users"); ucount = c.fetchone()[0]
    if ucount == 0:
        create_user("recruiter","recruiter123","Recruiter")
        create_user("candidate","candidate123","Candidate")
        create_user("rahul","rahul123","Candidate")
    c.execute("SELECT count(1) FROM candidates"); cc = c.fetchone()[0]
    if cc == 0:
        upsert_candidate_profile("candidate","Ananya Gupta","ananya@example.com","Bengaluru","Customer360",None,"1 month","Senior ML Engineer - built data platforms")
        add_education("candidate","St. Xavier's School","High School","2005-06-01","2010-04-30","CBSE - 90%")
        add_education("candidate","IIT Bombay","B.Tech CS","2010-08-01","2014-05-31","B.Tech in CS")
        add_project("candidate","Customer 360","BigBank","ML Engineer","Built ML pipelines and models","End-to-end ML platform","python,pandas,aws,nlp","2021-01-01","2023-06-30")
        add_project("candidate","Data Ingest","DataCorp","Data Engineer","Streaming ingestion","Kafka-based pipelines","python,spark,kafka","2019-01-01","2020-12-31")
        # Rahul
        upsert_candidate_profile("rahul","Rahul Mehta","rahul@example.com","Hyderabad","ShopX",None,"Immediate","Full-stack dev - React/Node")
        add_project("rahul","ShopX Frontend","ShopX","Senior Engineer","Frontend & micro-frontends","React-based storefront","react,node,aws,kubernetes","2022-01-01",None)
    conn.commit(); conn.close()

# ---------- UI helpers ----------
def timeline_plot(username):
    # combine education + projects into timeline for visualization
    edu = get_education(username)
    proj = get_projects(username)
    rows = []
    for _, r in edu.iterrows():
        try:
            s = parser.parse(r['start_date'])
        except:
            s = None
        try:
            e = parser.parse(r['end_date']) if r['end_date'] else None
        except:
            e = None
        rows.append({"type":"Education","label":f"{r['degree']} @ {r['institution']}","start":s,"end":e,"details":r['notes']})
    for _, r in proj.iterrows():
        try:
            s = parser.parse(r['start_date'])
        except:
            s = None
        try:
            e = parser.parse(r['end_date']) if r['end_date'] else None
        except:
            e = None
        rows.append({"type":"Project","label":f"{r['project_name']} ({r['role']}) @ {r['client']}","start":s,"end":e,"details":f"Tech: {r['tech_stack']}\nResp: {r['responsibilities']}"})
    if not rows:
        return None
    df = pd.DataFrame(rows)
    # normalize absent dates
    df['start'] = df['start'].apply(lambda x: x if x is not None else datetime(2000,1,1))
    df['end'] = df['end'].apply(lambda x: x if x is not None else datetime.now())
    fig = px.timeline(df, x_start="start", x_end="end", y="label", color="type", hover_data=["details"])
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(height=400)
    return fig

def get_education(username):
    conn = get_conn(); df = pd.read_sql_query("SELECT * FROM education WHERE username=? ORDER BY start_date DESC", conn, params=(username,)); conn.close(); return df
def get_projects(username):
    conn = get_conn(); df = pd.read_sql_query("SELECT * FROM projects WHERE username=? ORDER BY start_date DESC", conn, params=(username,)); conn.close(); return df

# ---------- Streamlit App ----------
def main():
    st.set_page_config(page_title="TalentGraph Copilot - Full MVP", layout="wide")
    init_db(); seed_demo()

    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
        st.session_state.username = None
        st.session_state.role = None

    st.title("TalentGraph Copilot — Career Timeline & Recruiter Search")

    sidebar_menu = ["Home","About"]
    if not st.session_state.logged_in:
        sidebar_menu += ["Register","Login"]
    else:
        sidebar_menu += ["Dashboard","Logout"]
    choice = st.sidebar.selectbox("Menu", sidebar_menu)

    if choice == "Home":
        st.markdown("**Find qualified candidates by searching project experience, tech stack, and responsibilities.**")
        st.info("Demo seeded. Use `recruiter / recruiter123` or `candidate / candidate123` to test quickly.")

    elif choice == "About":
        st.markdown("TalentGraph Copilot - demo MVP for recruitment.")

    elif choice == "Register":
        st.header("Register (Candidate or Recruiter)")
        with st.form("reg", clear_on_submit=True):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            role = st.selectbox("Role", ["Candidate","Recruiter"])
            submitted = st.form_submit_button("Register")
            if submitted:
                ok = create_user(username, password, role)
                if ok:
                    st.success("Account created. Please Login.")
                    if role == "Candidate":
                        upsert_candidate_profile(username,"","","","",None,"Not open","")
                else:
                    st.error("Username already exists.")

    elif choice == "Login":
        st.header("Login")
        with st.form("login", clear_on_submit=False):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login")
            if submitted:
                role = verify_user(username, password)
                if role:
                    st.session_state.logged_in = True
                    st.session_state.username = username
                    st.session_state.role = role
                    st.success(f"Welcome {username} ({role})")
                    st.experimental_rerun() if hasattr(st, "experimental_rerun") else st.rerun()
                else:
                    st.error("Invalid credentials. (Try demo accounts)")

    elif choice == "Logout":
        st.session_state.logged_in = False
        st.session_state.username = None
        st.session_state.role = None
        st.success("Logged out.")
        st.experimental_rerun() if hasattr(st, "experimental_rerun") else st.rerun()

    elif choice == "Dashboard":
        if not st.session_state.logged_in:
            st.warning("Login required.")
            return
        role = st.session_state.role
        user = st.session_state.username

        if role == "Candidate":
            st.header("Candidate Dashboard")
            prof = pd.read_sql_query("SELECT * FROM candidates WHERE username=?", get_conn(), params=(user,))
            prof = prof.iloc[0].to_dict() if not prof.empty else {}
            with st.expander("Edit profile"):
                full_name = st.text_input("Full name", prof.get("full_name",""))
                email = st.text_input("Email", prof.get("email",""))
                location = st.text_input("Location", prof.get("location",""))
                current_employer = st.text_input("Current employer", prof.get("current_employer",""))
                notice_date = st.date_input("Notice given date (leave blank if none)", value=None)
                notice_iso = notice_date.isoformat() if notice_date and isinstance(notice_date, date) else prof.get("notice_given_date")
                availability = st.selectbox("Availability", ["Immediate","1 month","3 months","Not open"], index=0)
                summary = st.text_area("Profile summary", prof.get("summary",""))
                if st.button("Save profile"):
                    upsert_candidate_profile(user, full_name, email, location, current_employer, notice_iso, availability, summary)
                    st.success("Profile saved.")

            st.markdown("---")
            st.subheader("Add Education")
            with st.form("edu"):
                inst = st.text_input("Institution")
                degree = st.text_input("Degree")
                sdate = st.date_input("Start date", value=date(2015,1,1))
                edate_opt = st.selectbox("End date or Current", ["Specific date","Current"])
                if edate_opt == "Specific date":
                    edate = st.date_input("End date", value=date(2018,1,1)).isoformat()
                else:
                    edate = None
                notes = st.text_area("Notes")
                if st.form_submit_button("Add education"):
                    add_education(user, inst, degree, sdate.isoformat(), edate, notes)
                    st.success("Education added.")

            st.markdown("---")
            st.subheader("Add Project")
            with st.form("proj"):
                pname = st.text_input("Project name")
                client = st.text_input("Client")
                role_on_proj = st.text_input("Role / Responsibilities (short)")
                resp = st.text_area("Responsibilities (detailed)")
                desc = st.text_area("Description")
                techs = st.text_input("Tech stack (comma-separated)")
                ps_start = st.date_input("Start date", value=date(2020,1,1))
                ps_end_opt = st.selectbox("End date or Current", ["Specific date","Current"])
                if ps_end_opt == "Specific date":
                    ps_end = st.date_input("End date", value=date(2022,1,1)).isoformat()
                else:
                    ps_end = None
                if st.form_submit_button("Add project"):
                    add_project(user, pname, client, role_on_proj, resp, desc, techs, ps_start.isoformat(), ps_end)
                    st.success("Project added.")

            st.markdown("---")
            st.subheader("Your Timeline & Skills")
            proj_df = get_projects(user)
            edu_df = get_education(user)
            if proj_df.empty and edu_df.empty:
                st.info("No projects or education yet.")
            else:
                fig = timeline_plot(user)
                if fig:
                    st.plotly_chart(fig, use_container_width=True)
                # skills summary from projects
                skills = {}
                for _, r in proj_df.iterrows():
                    for t in [x.strip().lower() for x in str(r.get('tech_stack','')).split(",") if x.strip()]:
                        skills[t] = skills.get(t,0)+1
                if skills:
                    s_df = pd.DataFrame([{"skill":k,"count":v} for k,v in skills.items()]).sort_values("count",ascending=False)
                    st.table(s_df)

        elif role == "Recruiter":
            st.header("Recruiter Dashboard")
            st.subheader("Post a Job (form)")
            with st.form("job_form"):
                title = st.text_input("Job title")
                skills = st.text_input("Required skills (comma-separated)")
                desc = st.text_area("Description")
                if st.form_submit_button("Post job"):
                    add_job(user, title, skills, desc)
                    st.success("Job posted.")
            st.markdown("---")
            st.subheader("Bulk upload jobs (CSV)")
            st.write("CSV columns: title,skills,description")
            uploaded = st.file_uploader("Upload CSV", type=["csv"])
            if uploaded:
                df_jobs = pd.read_csv(uploaded)
                for _, r in df_jobs.iterrows():
                    add_job(user, r.get('title',''), r.get('skills',''), r.get('description',''))
                st.success("Jobs uploaded.")

            st.markdown("---")
            st.subheader("Search Candidates")
            col1,col2,col3 = st.columns(3)
            with col1:
                tech_q = st.text_input("Tech stack (comma-separated)", "python,aws")
            with col2:
                last_used_months = st.number_input("Last used in last (months) (0 = ignore)", min_value=0, value=12, step=1)
            with col3:
                resp_q = st.text_input("Responsibilities keyword", "")
            avail = st.selectbox("Availability", ["Any","Immediate","1 month","3 months"])
            loc = st.text_input("Location (optional)")
            if st.button("Search"):
                techs = [t.strip().lower() for t in tech_q.split(",") if t.strip()]
                lastm = last_used_months if last_used_months>0 else None
                df = search_candidates(techs=techs if techs else None, last_used_months=lastm, responsibilities_keyword=resp_q, availability=avail, location=loc)
                if df.empty:
                    st.warning("No matches found.")
                else:
                    st.success(f"Found {len(df)} candidates")
                    st.dataframe(df)
                    st.download_button("Export matches CSV", data=export_df_csv_bytes(df), file_name="matched_candidates.csv", mime="text/csv")
                    # view candidate details
                    sel = st.selectbox("Select candidate username", df['username'].tolist())
                    if sel:
                        prof = pd.read_sql_query("SELECT * FROM candidates WHERE username=?", get_conn(), params=(sel,))
                        if not prof.empty:
                            p = prof.iloc[0].to_dict()
                            st.write(f"**{p.get('full_name')}** - {p.get('location')} - {p.get('availability')}")
                            st.write(p.get('summary',''))
                            proj_df = get_projects(sel)
                            if not proj_df.empty:
                                st.table(proj_df[['project_name','client','role','tech_stack','start_date','end_date']])
                            edu_df = get_education(sel)
                            if not edu_df.empty:
                                st.table(edu_df[['institution','degree','start_date','end_date']])
    else:
        st.info("Select a menu option from sidebar.")

if __name__ == "__main__":
    main()
