import os
import requests
import streamlit as st
from dateutil import parser as dateparser
from datetime import datetime

# -------------------------------------------------------
# CONFIG: set this after deploying backend on Render
# Example: BACKEND_URL = "https://your-service.onrender.com"
# -------------------------------------------------------
BACKEND_URL = os.environ.get("BACKEND_URL", "https://YOUR-RENDER-URL-HERE")

st.set_page_config(page_title="Job Application Tracker", layout="wide")

def api_headers():
    token = st.session_state.get("token")
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}

def api_get(path, params=None):
    r = requests.get(f"{BACKEND_URL}{path}", headers=api_headers(), params=params, timeout=15)
    return r

def api_post(path, json=None):
    r = requests.post(f"{BACKEND_URL}{path}", headers=api_headers(), json=json, timeout=15)
    return r

def api_put(path, json=None):
    r = requests.put(f"{BACKEND_URL}{path}", headers=api_headers(), json=json, timeout=15)
    return r

def api_delete(path):
    r = requests.delete(f"{BACKEND_URL}{path}", headers=api_headers(), timeout=15)
    return r

def iso_or_none(dt):
    if not dt:
        return None
    if isinstance(dt, datetime):
        return dt.isoformat()
    return None

def pretty_dt(iso):
    if not iso:
        return ""
    try:
        return dateparser.isoparse(iso).strftime("%Y-%m-%d")
    except Exception:
        return str(iso)

def ensure_backend_configured():
    if "YOUR-RENDER-URL-HERE" in BACKEND_URL:
        st.warning("Set BACKEND_URL in the Streamlit app (or env var BACKEND_URL) to your Render backend URL.")
        st.stop()

# ---------------------------
# Sidebar: Auth
# ---------------------------
st.sidebar.title("Job Tracker")

ensure_backend_configured()

if "token" not in st.session_state:
    st.session_state.token = None
if "user_email" not in st.session_state:
    st.session_state.user_email = None

auth_tab = st.sidebar.radio("Account", ["Login", "Register"] if not st.session_state.token else ["Logged In"])

if not st.session_state.token:
    email = st.sidebar.text_input("Email", key="auth_email")
    pw = st.sidebar.text_input("Password (min 8 chars)", type="password", key="auth_pw")

    if auth_tab == "Register":
        if st.sidebar.button("Create Account"):
            r = api_post("/auth/register", json={"email": email, "password": pw})
            if r.status_code in (200, 201):
                data = r.json()
                st.session_state.token = data["access_token"]
                st.session_state.user_email = data["user"]["email"]
                st.success("Registered & logged in.")
                st.rerun()
            else:
                st.error(r.json().get("error", r.text))
    else:
        if st.sidebar.button("Login"):
            r = api_post("/auth/login", json={"email": email, "password": pw})
            if r.status_code == 200:
                data = r.json()
                st.session_state.token = data["access_token"]
                st.session_state.user_email = data["user"]["email"]
                st.success("Logged in.")
                st.rerun()
            else:
                st.error(r.json().get("error", r.text))
else:
    st.sidebar.success(f"Signed in as {st.session_state.user_email}")
    if st.sidebar.button("Log out"):
        st.session_state.token = None
        st.session_state.user_email = None
        st.rerun()

# If not logged in, stop here
if not st.session_state.token:
    st.title("Job Application Tracker")
    st.info("Log in or register to start tracking applications.")
    st.stop()

# ---------------------------
# Main UI
# ---------------------------
st.title("Job Application Tracker (MVP)")

# Pull meta (limits/statuses)
meta = {}
try:
    m = api_get("/meta")
    if m.status_code == 200:
        meta = m.json()
except Exception:
    pass

allowed_statuses = meta.get("allowed_statuses", ["Drafting", "Submitted", "Interview", "Offer", "Rejected", "Withdrawn"])
max_apps = meta.get("max_apps_per_user", 5)

tab = st.tabs(["Applications", "Deliverables", "Writing Bank"])

# ---------------------------
# Applications tab
# ---------------------------
with tab[0]:
    colA, colB = st.columns([2, 1])

    with colB:
        st.subheader("Create new application")
        with st.form("create_app"):
            company = st.text_input("Company*")
            role = st.text_input("Role*")
            link = st.text_input("Link (optional)")
            status = st.selectbox("Status", allowed_statuses, index=0)
            due = st.date_input("Due date (optional)", value=None)
            notes = st.text_area("Notes (optional)", height=100)

            submitted = st.form_submit_button("Add application")
            if submitted:
                payload = {
                    "company": company,
                    "role": role,
                    "link": link,
                    "status": status,
                    "due_date": due.isoformat() if due else None,
                    "notes": notes,
                }
                r = api_post("/applications", json=payload)
                if r.status_code in (200, 201):
                    st.success("Created.")
                    st.rerun()
                else:
                    st.error(r.json().get("error", r.text))

        st.caption(f"Limit: {max_apps} applications per user.")

    with colA:
        st.subheader("Your applications")
        q = st.text_input("Search (company/role/notes)")
        filter_status = st.selectbox("Filter by status", ["(any)"] + allowed_statuses, index=0)

        params = {}
        if q.strip():
            params["q"] = q.strip()
        if filter_status != "(any)":
            params["status"] = filter_status

        r = api_get("/applications", params=params)
        if r.status_code != 200:
            st.error(r.json().get("error", r.text))
        else:
            apps = r.json()["applications"]

            if not apps:
                st.info("No applications yet. Add one on the right.")
            else:
                # pick selection
                labels = [f"{a['company']} — {a['role']} ({a['status']})" for a in apps]
                idx = st.selectbox("Select an application to view/edit", range(len(apps)), format_func=lambda i: labels[i])

                a = apps[idx]
                st.markdown(f"### {a['company']} — {a['role']}")
                st.write(f"**Status:** {a['status']}")
                if a.get("link"):
                    st.write(f"**Link:** {a['link']}")
                if a.get("due_date"):
                    st.write(f"**Due:** {pretty_dt(a['due_date'])}")
                if a.get("submitted_date"):
                    st.write(f"**Submitted:** {pretty_dt(a['submitted_date'])}")

                st.write("**Notes:**")
                st.code(a.get("notes") or "", language="markdown")

                st.divider()
                st.subheader("Edit application")
                with st.form("edit_app"):
                    company2 = st.text_input("Company", value=a["company"])
                    role2 = st.text_input("Role", value=a["role"])
                    link2 = st.text_input("Link", value=a.get("link") or "")
                    status2 = st.selectbox("Status", allowed_statuses, index=allowed_statuses.index(a["status"]) if a["status"] in allowed_statuses else 0)
                    due2 = st.date_input("Due date", value=dateparser.isoparse(a["due_date"]).date() if a.get("due_date") else None)
                    submitted2 = st.date_input("Submitted date", value=dateparser.isoparse(a["submitted_date"]).date() if a.get("submitted_date") else None)
                    notes2 = st.text_area("Notes", value=a.get("notes") or "", height=140)

                    c1, c2, c3 = st.columns([1, 1, 2])
                    save = c1.form_submit_button("Save")
                    delete = c2.form_submit_button("Delete")

                    if save:
                        payload = {
                            "company": company2,
                            "role": role2,
                            "link": link2,
                            "status": status2,
                            "due_date": due2.isoformat() if due2 else None,
                            "submitted_date": submitted2.isoformat() if submitted2 else None,
                            "notes": notes2,
                        }
                        rr = api_put(f"/applications/{a['id']}", json=payload)
                        if rr.status_code == 200:
                            st.success("Saved.")
                            st.rerun()
                        else:
                            st.error(rr.json().get("error", rr.text))

                    if delete:
                        rr = api_delete(f"/applications/{a['id']}")
                        if rr.status_code == 200:
                            st.success("Deleted.")
                            st.rerun()
                        else:
                            st.error(rr.json().get("error", rr.text))

# ---------------------------
# Deliverables tab
# ---------------------------
with tab[1]:
    st.subheader("Deliverables")

    r = api_get("/applications")
    if r.status_code != 200:
        st.error(r.json().get("error", r.text))
    else:
        apps = r.json()["applications"]
        if not apps:
            st.info("Create an application first.")
        else:
            app_map = {f"{a['company']} — {a['role']}": a for a in apps}
            selected_label = st.selectbox("Application", list(app_map.keys()))
            selected_app = app_map[selected_label]

            # list deliverables
            rr = api_get(f"/applications/{selected_app['id']}/deliverables")
            if rr.status_code != 200:
                st.error(rr.json().get("error", rr.text))
            else:
                deliverables = rr.json()["deliverables"]

                left, right = st.columns([2, 1], gap="large")

                with right:
                    st.markdown("### Add deliverable")
                    with st.form("add_deliverable"):
                        title = st.text_input("Title*")
                        dtype = st.selectbox("Type", ["Essay", "Question", "Resume", "Cover Letter", "Form", "Other"])
                        due = st.date_input("Due date (optional)", value=None)
                        state = st.selectbox("State", ["Not started", "In progress", "Done"])
                        content = st.text_area("Content (optional)", height=120)
                        is_done = st.checkbox("Mark done", value=(state == "Done"))

                        submit = st.form_submit_button("Add")
                        if submit:
                            payload = {
                                "title": title,
                                "dtype": dtype,
                                "due_date": due.isoformat() if due else None,
                                "state": state,
                                "content": content,
                                "is_done": is_done,
                            }
                            rrr = api_post(f"/applications/{selected_app['id']}/deliverables", json=payload)
                            if rrr.status_code in (200, 201):
                                st.success("Added.")
                                st.rerun()
                            else:
                                st.error(rrr.json().get("error", rrr.text))

                with left:
                    st.markdown("### Current deliverables")
                    if not deliverables:
                        st.info("No deliverables yet.")
                    else:
                        # quick board-ish grouping
                        groups = {
                            "Not started": [],
                            "In progress": [],
                            "Done": [],
                        }
                        for d in deliverables:
                            key = d.get("state") if d.get("state") in groups else "Not started"
                            groups[key].append(d)

                        gcols = st.columns(3)
                        for i, key in enumerate(["Not started", "In progress", "Done"]):
                            with gcols[i]:
                                st.markdown(f"**{key}**")
                                for d in groups[key]:
                                    with st.expander(f"{d['title']} ({d['dtype']})", expanded=False):
                                        st.write(f"Due: {pretty_dt(d.get('due_date'))}")
                                        st.write(f"Done: {d.get('is_done')}")
                                        st.code(d.get("content") or "", language="markdown")

                                        with st.form(f"edit_deliv_{d['id']}"):
                                            title2 = st.text_input("Title", value=d["title"])
                                            dtype2 = st.selectbox("Type", ["Essay", "Question", "Resume", "Cover Letter", "Form", "Other"],
                                                                  index=["Essay", "Question", "Resume", "Cover Letter", "Form", "Other"].index(d["dtype"]) if d["dtype"] in ["Essay","Question","Resume","Cover Letter","Form","Other"] else 5)
                                            due2 = st.date_input("Due", value=dateparser.isoparse(d["due_date"]).date() if d.get("due_date") else None)
                                            state2 = st.selectbox("State", ["Not started", "In progress", "Done"],
                                                                  index=["Not started","In progress","Done"].index(d["state"]) if d["state"] in ["Not started","In progress","Done"] else 0)
                                            content2 = st.text_area("Content", value=d.get("content") or "", height=120)
                                            is_done2 = st.checkbox("Done", value=bool(d.get("is_done")))

                                            c1, c2 = st.columns([1, 1])
                                            save = c1.form_submit_button("Save")
                                            delete = c2.form_submit_button("Delete")

                                            if save:
                                                payload = {
                                                    "title": title2,
                                                    "dtype": dtype2,
                                                    "due_date": due2.isoformat() if due2 else None,
                                                    "state": state2,
                                                    "content": content2,
                                                    "is_done": is_done2,
                                                }
                                                u = api_put(f"/deliverables/{d['id']}", json=payload)
                                                if u.status_code == 200:
                                                    st.success("Saved.")
                                                    st.rerun()
                                                else:
                                                    st.error(u.json().get("error", u.text))

                                            if delete:
                                                u = api_delete(f"/deliverables/{d['id']}")
                                                if u.status_code == 200:
                                                    st.success("Deleted.")
                                                    st.rerun()
                                                else:
                                                    st.error(u.json().get("error", u.text))

# ---------------------------
# Writing bank tab
# ---------------------------
with tab[2]:
    st.subheader("Writing Bank (reusable essays/answers)")

    left, right = st.columns([2, 1], gap="large")

    with right:
        st.markdown("### Add writing")
        with st.form("add_writing"):
            title = st.text_input("Title*")
            tags = st.text_input("Tags (comma-separated, optional)")
            content = st.text_area("Content*", height=200)
            submit = st.form_submit_button("Add")

            if submit:
                r = api_post("/writing", json={"title": title, "tags": tags, "content": content})
                if r.status_code in (200, 201):
                    st.success("Added.")
                    st.rerun()
                else:
                    st.error(r.json().get("error", r.text))

    with left:
        q = st.text_input("Search writing (title/tags/content)")
        rr = api_get("/writing", params={"q": q} if q.strip() else None)
        if rr.status_code != 200:
            st.error(rr.json().get("error", rr.text))
        else:
            items = rr.json()["items"]
            if not items:
                st.info("No writing saved yet.")
            else:
                for w in items:
                    with st.expander(f"{w['title']}  •  {w.get('tags') or ''}".strip(), expanded=False):
                        st.code(w["content"], language="markdown")

                        with st.form(f"edit_w_{w['id']}"):
                            title2 = st.text_input("Title", value=w["title"])
                            tags2 = st.text_input("Tags", value=w.get("tags") or "")
                            content2 = st.text_area("Content", value=w["content"], height=180)

                            c1, c2 = st.columns([1, 1])
                            save = c1.form_submit_button("Save")
                            delete = c2.form_submit_button("Delete")

                            if save:
                                u = api_put(f"/writing/{w['id']}", json={"title": title2, "tags": tags2, "content": content2})
                                if u.status_code == 200:
                                    st.success("Saved.")
                                    st.rerun()
                                else:
                                    st.error(u.json().get("error", u.text))

                            if delete:
                                u = api_delete(f"/writing/{w['id']}")
                                if u.status_code == 200:
                                    st.success("Deleted.")
                                    st.rerun()
                                else:
                                    st.error(u.json().get("error", u.text))
