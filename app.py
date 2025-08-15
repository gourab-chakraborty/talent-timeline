import streamlit as st
import sqlite3
import hashlib
import pandas as pd

# ---------------- DATABASE FUNCTIONS ----------------
def get_conn():
    return sqlite3.connect("talentgraph.db")

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            role TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS profiles (
            username TEXT PRIMARY KEY,
            skills TEXT,
            projects TEXT,
            timeline TEXT,
            availability TEXT,
            FOREIGN KEY(username) REFERENCES users(username)
        )
    """)
    conn.commit()
    conn.close()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def add_user(username, password, role):
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                  (username, hash_password(password), role))
        conn.commit()
    except sqlite3.IntegrityError:
        st.warning("Username already exists!")
    conn.close()

def verify_user(username, password):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT role FROM users WHERE username = ? AND password = ?",
              (username, hash_password(password)))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

def save_profile(username, skills, projects, timeline, availability):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO profiles (username, skills, projects, timeline, availability)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(username) DO UPDATE SET
        skills=excluded.skills,
        projects=excluded.projects,
        timeline=excluded.timeline,
        availability=excluded.availability
    """, (username, skills, projects, timeline, availability))
    conn.commit()
    conn.close()

def get_all_profiles():
    conn = get_conn()
    df = pd.read_sql("SELECT * FROM profiles", conn)
    conn.close()
    return df

def get_profile(username):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM profiles WHERE username=?", (username,))
    result = c.fetchone()
    conn.close()
    return result

# ---------------- INITIALIZATION ----------------
init_db()

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.username = None
    st.session_state.role = None

# ---------------- UI ----------------
st.title("💼 TalentGraph Copilot - MVP Demo")

if not st.session_state.logged_in:
    choice = st.radio("Select an option:", ["Login", "Register"])

    if choice == "Login":
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.button("Login"):
            role = verify_user(username, password)
            if role:
                st.session_state.logged_in = True
                st.session_state.username = username
                st.session_state.role = role
                st.success(f"Welcome, {username} ({role})!")
                st.experimental_rerun()
            else:
                st.error("Invalid credentials")

    elif choice == "Register":
        username = st.text_input("Choose a Username")
        password = st.text_input("Choose a Password", type="password")
        role = st.selectbox("Role", ["Recruiter", "Candidate"])
        if st.button("Register"):
            add_user(username, password, role)
            st.success("Account created! Please log in.")

else:
    st.write(f"Hello **{st.session_state.username}**! You are logged in as **{st.session_state.role}**.")

    if st.session_state.role == "Candidate":
        st.subheader("📌 Candidate Profile Setup / Edit")
        skills = st.text_area("Skills (comma separated)", placeholder="Python, AI, Data Science")
        projects = st.text_area("Projects (comma separated)", placeholder="Project A, Project B")
        timeline = st.text_area("Career Timeline (comma separated years)", placeholder="2019 - Joined TCS, 2021 - Promoted...")
        availability = st.selectbox("Availability", ["Available", "Allocated"])

        if st.button("Save Profile"):
            save_profile(st.session_state.username, skills, projects, timeline, availability)
            st.success("Profile saved successfully!")

        st.subheader("📄 Your Profile Preview")
        profile = get_profile(st.session_state.username)
        if profile:
            st.json({
                "Skills": profile[1],
                "Projects": profile[2],
                "Timeline": profile[3],
                "Availability": profile[4]
            })

    elif st.session_state.role == "Recruiter":
        st.subheader("🔍 Recruiter Dashboard - Search Candidates")
        profiles_df = get_all_profiles()

        if not profiles_df.empty:
            skill_filter = st.text_input("Search by Skill")
            availability_filter = st.selectbox("Filter by Availability", ["All", "Available", "Allocated"])

            filtered_df = profiles_df.copy()
            if skill_filter:
                filtered_df = filtered_df[filtered_df["skills"].str.contains(skill_filter, case=False, na=False)]
            if availability_filter != "All":
                filtered_df = filtered_df[filtered_df["availability"] == availability_filter]

            st.dataframe(filtered_df)
        else:
            st.warning("No candidate profiles found.")

    if st.button("Logout"):
        st.session_state.logged_in = False
        st.session_state.username = None
        st.session_state.role = None
        st.success("Logged out successfully.")
        st.experimental_rerun()
