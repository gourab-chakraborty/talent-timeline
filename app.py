import streamlit as st
import sqlite3

# ------------------ DATABASE ------------------
def init_db():
    conn = sqlite3.connect('talentgraph.db')
    c = conn.cursor()

    # Users table
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            role TEXT
        )
    ''')

    # Candidate profiles
    c.execute('''
        CREATE TABLE IF NOT EXISTS candidates (
            user_id INTEGER,
            skills TEXT,
            projects TEXT,
            availability TEXT,
            timeline TEXT
        )
    ''')
    conn.commit()
    conn.close()

# ------------------ AUTH ------------------
def register(username, password, role):
    conn = sqlite3.connect('talentgraph.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", 
                  (username, password, role))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def login(username, password):
    conn = sqlite3.connect('talentgraph.db')
    c = conn.cursor()
    c.execute("SELECT id, role FROM users WHERE username = ? AND password = ?", (username, password))
    user = c.fetchone()
    conn.close()
    return user

# ------------------ CANDIDATE ------------------
def update_candidate_profile(user_id, skills, projects, availability, timeline):
    conn = sqlite3.connect('talentgraph.db')
    c = conn.cursor()
    c.execute("DELETE FROM candidates WHERE user_id = ?", (user_id,))
    c.execute(
        "INSERT INTO candidates (user_id, skills, projects, availability, timeline) VALUES (?, ?, ?, ?, ?)",
        (user_id, skills, projects, availability, timeline)
    )
    conn.commit()
    conn.close()

# ------------------ RECRUITER ------------------
def search_candidates(skill_keyword):
    conn = sqlite3.connect('talentgraph.db')
    c = conn.cursor()
    c.execute("SELECT u.username, c.skills, c.projects, c.availability, c.timeline \
               FROM candidates c JOIN users u ON c.user_id = u.id \
               WHERE c.skills LIKE ?", (f"%{skill_keyword}%",))
    results = c.fetchall()
    conn.close()
    return results

# ------------------ APP ------------------
def main():
    st.set_page_config(page_title="Talent Timeline", layout="wide")
    st.title("Talent Timeline Portal")

    menu = ["Login", "Register"]
    choice = st.sidebar.selectbox("Menu", menu)

    if choice == "Register":
        st.subheader("Create New Account")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        role = st.selectbox("Role", ["Candidate", "Recruiter"])
        if st.button("Register"):
            if register(username, password, role):
                st.success("Registration successful! Please login.")
            else:
                st.error("Username already exists.")

    elif choice == "Login":
        st.subheader("Login to Your Account")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.button("Login"):
            user = login(username, password)
            if user:
                user_id, role = user
                st.session_state.user_id = user_id
                st.session_state.role = role
                st.success(f"Welcome {username} ({role})")
                
                if role == "Candidate":
                    skills = st.text_area("Your Skills (comma separated)")
                    projects = st.text_area("Projects Worked On")
                    availability = st.selectbox("Availability", ["Available", "Not Available"])
                    timeline = st.text_area("Career Timeline")
                    if st.button("Save Profile"):
                        update_candidate_profile(user_id, skills, projects, availability, timeline)
                        st.success("Profile updated successfully!")

                elif role == "Recruiter":
                    st.subheader("Search Candidates")
                    keyword = st.text_input("Search by Skill")
                    if st.button("Search"):
                        results = search_candidates(keyword)
                        if results:
                            for r in results:
                                st.write(f"**{r[0]}**")
                                st.write(f"Skills: {r[1]}")
                                st.write(f"Projects: {r[2]}")
                                st.write(f"Availability: {r[3]}")
                                st.write(f"Timeline: {r[4]}")
                                st.markdown("---")
                        else:
                            st.warning("No matching candidates found.")
            else:
                st.error("Invalid credentials.")

if __name__ == '__main__':
    init_db()
    main()
