"""
Talent Timeline MVP - Streamlit single-file app with SQLite backend.

Features:
- Candidate mode: create / edit profile with timeline events and skills
- Recruiter mode: search candidates by skills, experience, availability
- Timeline visualization and skill summary
- Mock data seeded on first run
- Export search results as CSV for outreach

Run:
    pip install -r requirements.txt
    streamlit run app.py
"""

import streamlit as st
import pandas as pd
import numpy as np
import sqlite3
from datetime import datetime, date
import plotly.express as px
import os
import io
from dateutil import parser

DB_PATH = "talent_timeline.db"

# ---------- DB helpers ----------
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS candidate (
        id TEXT PRIMARY KEY,
        name TEXT,
        email TEXT,
        location TEXT,
        open_to_work TEXT,  -- immediate/1 month/3 months/no
        profile_text TEXT,
        created_at TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS timeline_event (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        candidate_id TEXT,
        title TEXT,
        company TEXT,
        start_date TEXT,
        end_date TEXT,
        skills TEXT  -- comma-separated
    )
    """)
    conn.commit()
    conn.close()

def seed_mock_data():
    # Only seed if no candidates exist
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT count(1) FROM candidate")
    cnt = cur.fetchone()[0]
    if cnt > 0:
        conn.close()
        return
    # Mock candidates
    now = datetime.utcnow().isoformat()
    candidates = [
        ("C001","Ananya Gupta","ananya@example.com","Bengaluru","1 month","Senior ML Engineer - built data platforms and ML services","" , now),
        ("C002","Rahul Mehta","rahul@example.com","Hyderabad","Immediate","Full-stack dev - React/Node/Kubernetes","", now),
        ("C003","Priya Iyer","priya@example.com","Chennai","3 months","Salesforce specialist with integrations experience","", now),
        ("C004","Vikram Singh","vikram@example.com","Pune","Immediate","Java microservices & AWS; fintech projects", "", now),
        ("C005","Meera Shah","meera@example.com","Mumbai","1 month","Data engineer (Python, Spark, SQL) with streaming experience","", now),
    ]
    cur.executemany("INSERT OR REPLACE INTO candidate (id,name,email,location,open_to_work,profile_text,created_at) VALUES (?,?,?,?,?,?,?)",
                    [(c[0],c[1],c[2],c[3],c[4],c[5],c[7]) for c in candidates])
    # Timeline events with skills
    events = [
        # Ananya
        ("C001","ML Engineer","Customer360","2021-01-01","2023-06-30","python,pytorch,pandas,nlp,aws"),
        ("C001","Data Engineer","DataCorp","2019-01-01","2020-12-31","python,spark,sql"),
        # Rahul
        ("C002","Senior Engineer","ShopX","2022-01-01",None,"react,node,aws,kubernetes"),
        ("C002","Engineer","WebStart","2019-06-01","2021-12-31","javascript,react"),
        # Priya
        ("C003","Salesforce Consultant","CloudCRM","2020-03-01",None,"salesforce,soql,javascript"),
        ("C003","Integration Lead","BizSoft","2017-05-01","2019-12-31","sap,salesforce,java"),
        # Vikram
        ("C004","Lead Developer","FinBank","2023-02-01",None,"java,spring,aws"),
        ("C004","Developer","AlphaTech","2018-04-01","2022-10-31","java,microservices"),
        # Meera
        ("C005","Data Engineer","StreamWorks","2021-08-01",None,"python,spark,kafka"),
        ("C005","Analyst","RetailCo","2017-09-01","2020-12-31","sql,etl"),
    ]
    cur.executemany("INSERT INTO timeline_event (candidate_id,title,company,start_date,end_date,skills) VALUES (?,?,?,?,?,?)",
                    events)
    conn.commit()
    conn.close()

# ---------- Data functions ----------
def upsert_candidate(row):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    INSERT OR REPLACE INTO candidate (id,name,email,location,open_to_work,profile_text,created_at)
    VALUES (?,?,?,?,?,?,?)
    """, (row['id'], row['name'], row['email'], row['location'], row['open_to_work'], row['profile_text'], row.get('created_at', datetime.utcnow().isoformat())))
    conn.commit()
    conn.close()

def add_timeline_event(candidate_id, title, company, start_date, end_date, skills):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO timeline_event(candidate_id,title,company,start_date,end_date,skills)
    VALUES (?,?,?,?,?,?)
    """, (candidate_id, title, company, start_date, end_date, ",".join([s.strip().lower() for s in skills])))
    conn.commit()
    conn.close()

def get_all_candidates_df():
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM candidate", conn)
    conn.close()
    return df

def get_timeline_df(candidate_id):
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM timeline_event WHERE candidate_id = ? ORDER BY start_date", conn, params=(candidate_id,))
    conn.close()
    return df

def search_candidates(skills=None, min_years=None, availability=None, location=None):
    # skills: list[str]; min_years: float; availability: immediate/1 month/3 months/None
    # Build simple filter by scanning timelines and skills
    candidates = get_all_candidates_df()
    out_rows = []
    for _, row in candidates.iterrows():
        cid = row['id']
        tdf = get_timeline_df(cid)
        # compute experience years (sum of durations)
        total_days = 0
        for _, ev in tdf.iterrows():
            s = ev['start_date']
            e = ev['end_date'] if ev['end_date'] and ev['end_date'] != 'None' else date.today().isoformat()
            try:
                s_dt = parser.parse(s).date()
            except:
                s_dt = date.today()
            try:
                e_dt = parser.parse(e).date()
            except:
                e_dt = date.today()
            total_days += (e_dt - s_dt).days
        years = total_days / 365.0
        # skills matching
        match = True
        skill_matches = []
        if skills:
            skill_matches = []
            for sk in skills:
                found = False
                for _, ev in tdf.iterrows():
                    ev_sk = (ev['skills'] or "")
                    if sk.strip().lower() in [x.strip().lower() for x in ev_sk.split(",") if x.strip()]:
                        found = True
                        break
                if found:
                    skill_matches.append(sk)
            if len(skill_matches) < len(skills):
                match = False
        # availability filter
        avail_ok = True
        if availability and availability != "Any":
            avail_ok = (row.get('open_to_work','').lower().startswith(availability.lower()))
        # location
        loc_ok = True
        if location and location.strip() != "":
            loc_ok = (location.strip().lower() in (row.get('location','').lower()))
        if match and avail_ok and loc_ok:
            out_rows.append({
                "id": cid,
                "name": row['name'],
                "email": row['email'],
                "location": row['location'],
                "open_to_work": row['open_to_work'],
                "years_experience": round(years,2),
                "profile_text": row['profile_text'],
                "skill_matches": ",".join(skill_matches)
            })
    df = pd.DataFrame(out_rows)
    return df

# ---------- UI helpers ----------
def timeline_plot(tdf, candidate_name):
    if tdf.empty:
        return None
    # create Gantt-like dataframe
    df = tdf.copy()
    df['start'] = pd.to_datetime(df['start_date'])
    # For open jobs (no end date), use today
    df['end'] = df['end_date'].apply(lambda x: pd.to_datetime(x) if x and str(x).lower() != 'none' else pd.to_datetime(date.today().isoformat()))
    df['duration_days'] = (df['end'] - df['start']).dt.days
    fig = px.timeline(df, x_start="start", x_end="end", y="company", color="title", hover_data=["skills"])
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(height=350, margin=dict(l=20, r=20, t=30, b=20), title=f"Career timeline — {candidate_name}")
    return fig

def skills_summary(tdf):
    # Build skills frequency & recency approximation
    skills = {}
    for _, ev in tdf.iterrows():
        sks = (ev['skills'] or "")
        if not isinstance(sks, str):
            continue
        for s in [x.strip().lower() for x in sks.split(",") if x.strip()]:
            skills[s] = skills.get(s, 0) + 1
    if not skills:
        return None
    s_df = pd.DataFrame([{"skill":k,"count":v} for k,v in skills.items()]).sort_values("count", ascending=False)
    return s_df

# ---------- Streamlit UI ----------
st.set_page_config(page_title="Talent Timeline MVP", layout="wide")
init_db()
seed_mock_data()

st.title("Talent Timeline — Recruiter & Candidate MVP")
st.markdown("**One dashboard to view career journeys & search for skill-matched candidates.**")

mode = st.sidebar.selectbox("Mode", ["Recruiter (Search)", "Candidate (Create / Edit)", "Admin (Seed CSV / Export)"])

if mode == "Candidate (Create / Edit)":
    st.header("Candidate: Create / Edit Profile")
    col1, col2 = st.columns([2,1])
    with col1:
        candidate_id = st.text_input("Candidate ID (unique)", "C006")
        name = st.text_input("Full name", "Your Name")
        email = st.text_input("Email", "you@example.com")
        location = st.text_input("Location", "City")
        open_to_work = st.selectbox("Availability", ["Immediate","1 month","3 months","Not open"])
        profile_text = st.text_area("Short summary / profile text", "Experienced in ...")
    with col2:
        st.write("Tip: Add timeline events (projects / roles) with skills used.")
        if st.button("Save Profile"):
            upsert_candidate({"id":candidate_id,"name":name,"email":email,"location":location,"open_to_work":open_to_work,"profile_text":profile_text})
            st.success("Profile saved. Add timeline events below.")
    st.markdown("---")
    st.subheader("Add timeline event")
    with st.form("timeline_form"):
        c_id = st.text_input("Candidate ID for event", candidate_id)
        title = st.text_input("Role / Title", "Software Engineer")
        company = st.text_input("Company / Project", "Acme Ltd")
        start = st.date_input("Start date", datetime(2021,1,1).date())
        end_option = st.selectbox("End date / Current", ["Current","Specific date"])
        if end_option == "Specific date":
            end = st.date_input("End date", datetime(2022,12,31).date())
            end_val = end.isoformat()
        else:
            end_val = None
        skills = st.text_input("Skills (comma-separated)", "python,sql")
        submitted = st.form_submit_button("Add event")
    if submitted:
        add_timeline_event(c_id, title, company, start.isoformat(), end_val, [s.strip() for s in skills.split(",") if s.strip()])
        st.success("Timeline event added.")
    st.markdown("---")
    st.subheader("View your timeline")
    cid_view = st.text_input("Enter Candidate ID to view", candidate_id)
    if st.button("Load Timeline"):
        tdf = get_timeline_df(cid_view)
        cand = pd.DataFrame([r for _,r in get_all_candidates_df().set_index('id').T.to_dict().items()]).T if False else None
        if tdf.empty:
            st.info("No timeline events for this candidate yet.")
        else:
            st.plotly_chart(timeline_plot(tdf, cid_view), use_container_width=True)
            ssum = skills_summary(tdf)
            if ssum is not None:
                st.write("Skill summary")
                st.table(ssum)

elif mode == "Recruiter (Search)":
    st.header("Recruiter: Search Candidates")
    col1, col2, col3 = st.columns(3)
    with col1:
        skill_q = st.text_input("Skills (comma-separated)", "python,aws")
    with col2:
        min_years = st.number_input("Min Years Experience (approx)", min_value=0.0, max_value=30.0, value=2.0, step=0.5)
    with col3:
        availability = st.selectbox("Availability", ["Any","Immediate","1 month","3 months"])
    loc = st.text_input("Location (optional)", "")
    if st.button("Search"):
        skills = [s.strip().lower() for s in skill_q.split(",") if s.strip()]
        df = search_candidates(skills=skills if skills else None, min_years=min_years, availability=availability, location=loc)
        if df.empty:
            st.warning("No candidates matched your filters. Try relaxing filters or change skills.")
        else:
            st.success(f"Found {len(df)} candidates")
            st.dataframe(df[["id","name","location","open_to_work","years_experience","skill_matches"]])
            with st.expander("Export results as CSV"):
                csv = df.to_csv(index=False)
                b = csv.encode()
                st.download_button("Download CSV", data=b, file_name="search_results.csv", mime="text/csv")
            st.markdown("---")
            st.write("Click a candidate to view their timeline & skills")
            sel = st.selectbox("Select candidate", df['id'].tolist())
            if sel:
                tdf = get_timeline_df(sel)
                candidate_row = get_all_candidates_df().set_index('id').loc[sel]
                st.subheader(f"{candidate_row['name']} — {candidate_row['location']} — {candidate_row['open_to_work']}")
                st.write("Profile summary:")
                st.write(candidate_row['profile_text'])
                fig = timeline_plot(tdf, candidate_row['name'])
                if fig:
                    st.plotly_chart(fig, use_container_width=True)
                ssum = skills_summary(tdf)
                if ssum is not None:
                    st.write("Skills (approx frequency in timeline)")
                    st.table(ssum)
                st.markdown("**Contact template (copy/paste email)**")
                contact_text = f"""Hi {candidate_row['name']},

I’m [Your Name], a recruiter at [Company]. Based on your experience with {skill_q}, we think you could be a great fit for a role on our team. Are you available for a short call?

Regards,
[Your Name]"""
                st.code(contact_text)
    st.markdown("---")
    st.write("Tip: seed the platform with more candidate profiles to make search results richer.")

else:  # Admin
    st.header("Admin: Data export & seed")
    if st.button("Export all candidates as CSV"):
        df = get_all_candidates_df()
        buff = io.StringIO()
        df.to_csv(buff, index=False)
        st.download_button("Download candidates.csv", data=buff.getvalue().encode(), file_name="all_candidates.csv")
    if st.button("Export full timelines"):
        # Merge timelines & candidates
        conn = get_conn()
        df_c = pd.read_sql_query("SELECT * FROM candidate", conn)
        df_t = pd.read_sql_query("SELECT * FROM timeline_event", conn)
        merged = df_t.merge(df_c, left_on="candidate_id", right_on="id", how="left")
        buf = io.StringIO()
        merged.to_csv(buf, index=False)
        st.download_button("Download timelines.csv", data=buf.getvalue().encode(), file_name="timelines.csv")
    st.markdown("Seed more mock data if needed")
    if st.button("Add 20 synthetic demo candidates"):
        # Add synthetic
        for i in range(20):
            cid = f"X{100+i}"
            upsert_candidate({"id":cid,"name":f"Demo {i}","email":f"demo{i}@example.com","location":"Bengaluru","open_to_work":"Immediate","profile_text":"Demo candidate","created_at":datetime.utcnow().isoformat()})
            add_timeline_event(cid,"Engineer","DemoCorp","2019-01-01",None,["python","sql"])
        st.success("Added 20 demo candidates.")
    st.markdown("You can also delete DB file to reset: (not exposed via UI).")

st.markdown("---")
st.caption("MVP: Talent Timeline — structured profiles for fast recruiter search. Built for demo & early adopter testing.")
