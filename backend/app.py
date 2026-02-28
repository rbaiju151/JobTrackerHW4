import os
import re
from datetime import datetime, timedelta, timezone

from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required, get_jwt_identity
)
from sqlalchemy import (
    create_engine, Column, Integer, String, DateTime, Text, ForeignKey, Boolean, func
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from werkzeug.security import generate_password_hash, check_password_hash
from google import genai
from google.genai import types

# -----------------------
# Config
# -----------------------
MAX_USERS_TOTAL = 10
MAX_APPS_PER_USER = 5

DEFAULT_STATUSES = [
    "Drafting",
    "Submitted",
    "Interview",
    "Offer",
    "Rejected",
    "Withdrawn",
]

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///jobtracker.db")
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-me")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

ai_client = genai.Client(api_key=GEMINI_API_KEY) # This line activates the api key stored as an environment variable in Render

# Render sometimes provides postgres URLs like postgres:// -> needs postgresql:// for SQLAlchemy
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

# -----------------------
# Models
# -----------------------
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    applications = relationship("Application", back_populates="user", cascade="all, delete-orphan")
    writing_bank_items = relationship("WritingBankItem", back_populates="user", cascade="all, delete-orphan")


class Application(Base):
    __tablename__ = "applications"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    company = Column(String(200), nullable=False)
    role = Column(String(200), nullable=False)
    link = Column(String(1000), nullable=True)
    status = Column(String(50), nullable=False, default="Drafting")

    due_date = Column(DateTime, nullable=True)
    submitted_date = Column(DateTime, nullable=True)

    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    user = relationship("User", back_populates="applications")
    deliverables = relationship("Deliverable", back_populates="application", cascade="all, delete-orphan")


class Deliverable(Base):
    __tablename__ = "deliverables"
    id = Column(Integer, primary_key=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=False, index=True)

    title = Column(String(200), nullable=False)
    dtype = Column(String(50), nullable=False, default="Other")  # Essay / Question / Resume / Cover Letter / Form / Other
    due_date = Column(DateTime, nullable=True)

    state = Column(String(50), nullable=False, default="Not started")  # Not started / In progress / Done
    content = Column(Text, nullable=True)  # essay draft / answers
    is_done = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    application = relationship("Application", back_populates="deliverables")


class WritingBankItem(Base):
    __tablename__ = "writing_bank"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    title = Column(String(200), nullable=False)
    tags = Column(String(500), nullable=True)  # comma-separated tags
    content = Column(Text, nullable=False)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    user = relationship("User", back_populates="writing_bank_items")


Base.metadata.create_all(bind=engine)

# -----------------------
# Helpers
# -----------------------
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

def parse_iso_datetime(value):
    """Accepts ISO strings like '2026-02-14' or '2026-02-14T18:30:00' (naive treated as UTC)."""
    if not value:
        return None
    if isinstance(value, (int, float)):
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        # Allow date-only
        if len(s) == 10 and s[4] == "-" and s[7] == "-":
            dt = datetime.fromisoformat(s + "T00:00:00")
        else:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None

def dt_to_iso(dt):
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def app_to_dict(a: Application):
    return {
        "id": a.id,
        "company": a.company,
        "role": a.role,
        "link": a.link,
        "status": a.status,
        "due_date": dt_to_iso(a.due_date),
        "submitted_date": dt_to_iso(a.submitted_date),
        "notes": a.notes,
        "created_at": dt_to_iso(a.created_at),
        "updated_at": dt_to_iso(a.updated_at),
    }

def deliverable_to_dict(d: Deliverable):
    return {
        "id": d.id,
        "application_id": d.application_id,
        "title": d.title,
        "dtype": d.dtype,
        "due_date": dt_to_iso(d.due_date),
        "state": d.state,
        "is_done": d.is_done,
        "content": d.content,
        "created_at": dt_to_iso(d.created_at),
        "updated_at": dt_to_iso(d.updated_at),
    }

def writing_item_to_dict(w: WritingBankItem):
    return {
        "id": w.id,
        "title": w.title,
        "tags": w.tags,
        "content": w.content,
        "created_at": dt_to_iso(w.created_at),
        "updated_at": dt_to_iso(w.updated_at),
    }

# -----------------------
# App
# -----------------------
app = Flask(__name__)
app.config["JWT_SECRET_KEY"] = JWT_SECRET
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(days=7)

CORS(app, resources={r"/*": {"origins": "*"}})
jwt = JWTManager(app)

@app.get("/health")
def health():
    return jsonify({"ok": True})

@app.get("/meta")
def meta():
    return jsonify({
        "max_users_total": MAX_USERS_TOTAL,
        "max_apps_per_user": MAX_APPS_PER_USER,
        "allowed_statuses": DEFAULT_STATUSES,
    })

# -----------------------
# Auth endpoints
# -----------------------
@app.post("/auth/register")
def register():
    data = request.get_json(force=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not EMAIL_RE.match(email):
        return jsonify({"error": "Invalid email"}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400

    db = SessionLocal()
    try:
        total_users = db.query(func.count(User.id)).scalar() or 0
        if total_users >= MAX_USERS_TOTAL:
            return jsonify({"error": "User limit reached (10 total)."}), 403

        existing = db.query(User).filter(User.email == email).first()
        if existing:
            return jsonify({"error": "Email already registered"}), 409

        u = User(email=email, password_hash=generate_password_hash(password))
        db.add(u)
        db.commit()
        db.refresh(u)

        token = create_access_token(
            identity=str(u.id),
            additional_claims={"email": u.email}
        )
        return jsonify({"access_token": token, "user": {"id": u.id, "email": u.email}}), 201
    finally:
        db.close()

@app.post("/auth/login")
def login():
    data = request.get_json(force=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == email).first()
        if not u or not check_password_hash(u.password_hash, password):
            return jsonify({"error": "Invalid credentials"}), 401

        token = create_access_token(
            identity=str(u.id),
            additional_claims={"email": u.email}
        )
        return jsonify({"access_token": token, "user": {"id": u.id, "email": u.email}})
    finally:
        db.close()

# -----------------------
# Applications
# -----------------------
@app.get("/applications")
@jwt_required()
def list_applications():
    user_id = int(get_jwt_identity())


    status = request.args.get("status")
    q = (request.args.get("q") or "").strip().lower()

    db = SessionLocal()
    try:
        query = db.query(Application).filter(Application.user_id == user_id)
        if status:
            query = query.filter(Application.status == status)
        if q:
            like = f"%{q}%"
            query = query.filter(
                (Application.company.ilike(like)) | (Application.role.ilike(like)) | (Application.notes.ilike(like))
            )
        apps = query.order_by(Application.updated_at.desc()).all()
        return jsonify({"applications": [app_to_dict(a) for a in apps]})
    finally:
        db.close()

@app.post("/applications")
@jwt_required()
def create_application():
    user_id = int(get_jwt_identity())


    data = request.get_json(force=True) or {}
    company = (data.get("company") or "").strip()
    role = (data.get("role") or "").strip()
    link = (data.get("link") or "").strip() or None
    status = (data.get("status") or "Drafting").strip()
    due_date = parse_iso_datetime(data.get("due_date"))
    submitted_date = parse_iso_datetime(data.get("submitted_date"))
    notes = data.get("notes")

    if not company or not role:
        return jsonify({"error": "company and role are required"}), 400
    if status not in DEFAULT_STATUSES:
        return jsonify({"error": f"status must be one of {DEFAULT_STATUSES}"}), 400

    db = SessionLocal()
    try:
        count_apps = db.query(func.count(Application.id)).filter(Application.user_id == user_id).scalar() or 0
        if count_apps >= MAX_APPS_PER_USER:
            return jsonify({"error": "Application limit reached (5 per user)."}), 403

        a = Application(
            user_id=user_id,
            company=company,
            role=role,
            link=link,
            status=status,
            due_date=due_date,
            submitted_date=submitted_date,
            notes=notes,
            updated_at=datetime.now(timezone.utc),
        )
        db.add(a)
        db.commit()
        db.refresh(a)
        return jsonify({"application": app_to_dict(a)}), 201
    finally:
        db.close()

@app.get("/applications/<int:app_id>")
@jwt_required()
def get_application(app_id: int):
    user_id = int(get_jwt_identity())


    db = SessionLocal()
    try:
        a = db.query(Application).filter(Application.id == app_id, Application.user_id == user_id).first()
        if not a:
            return jsonify({"error": "Not found"}), 404
        return jsonify({"application": app_to_dict(a)})
    finally:
        db.close()

@app.put("/applications/<int:app_id>")
@jwt_required()
def update_application(app_id: int):
    user_id = int(get_jwt_identity())


    data = request.get_json(force=True) or {}

    db = SessionLocal()
    try:
        a = db.query(Application).filter(Application.id == app_id, Application.user_id == user_id).first()
        if not a:
            return jsonify({"error": "Not found"}), 404

        if "company" in data:
            a.company = (data.get("company") or "").strip() or a.company
        if "role" in data:
            a.role = (data.get("role") or "").strip() or a.role
        if "link" in data:
            a.link = (data.get("link") or "").strip() or None
        if "status" in data:
            status = (data.get("status") or "").strip()
            if status not in DEFAULT_STATUSES:
                return jsonify({"error": f"status must be one of {DEFAULT_STATUSES}"}), 400
            a.status = status
        if "due_date" in data:
            a.due_date = parse_iso_datetime(data.get("due_date"))
        if "submitted_date" in data:
            a.submitted_date = parse_iso_datetime(data.get("submitted_date"))
        if "notes" in data:
            a.notes = data.get("notes")

        a.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(a)
        return jsonify({"application": app_to_dict(a)})
    finally:
        db.close()

@app.delete("/applications/<int:app_id>")
@jwt_required()
def delete_application(app_id: int):
    user_id = int(get_jwt_identity())


    db = SessionLocal()
    try:
        a = db.query(Application).filter(Application.id == app_id, Application.user_id == user_id).first()
        if not a:
            return jsonify({"error": "Not found"}), 404
        db.delete(a)
        db.commit()
        return jsonify({"deleted": True})
    finally:
        db.close()

# This is my main manual coded section. I did my best to use a similar format to the earlier functions AI had helped me create because they both worked well and because 
# much of the code is standard stuff for interacting with the Postgres db, handling incoming data from the frontend, etc. I did have AI look at it and help me with it, but I can 
# confidently explain what each line does in detail

@app.post("/applications/<int:app_id>/chat") # Creates new URL endpoint, uses dynamic link to match application ID based on what application you are chatting about
@jwt_required() # Uses the jwt authentication to ensure the user is logged in with valid credentials that are stored in the database
def application_chat(app_id: int):
    user_id = int(get_jwt_identity()) # Actually pulls the credentials and ensures we are using the right data associated with the logged in account
    data = request.get_json(force=True) or {} # Parses data coming from the frontend as json, force=True forces the method to read it as json even if not. Returns empty dictionary is data from frontend is empty
    
    user_message = data.get("message") # Pulls the latest message the user sent to the chatbot from the data variable
    chat_history = data.get("history", []) # Pulls chat history to parse into Gemini, returns empty list if this is the first message

    if not user_message: # Added these later as debugging checks to help me solve issues. if either the user message or the api key is not filled, instead of crashing these give a clean error message
        return jsonify({"error": "Message is required"}), 400
    if not GEMINI_API_KEY:
        return jsonify({"error": "GEMINI_API_KEY is not configured on the server."}), 500

    db = SessionLocal() # connection to Postgres db
    try: # use try except framework as with the rest of the app to handle errors
        a = db.query(Application).filter(Application.id == app_id, Application.user_id == user_id).first() # Query the database to pull the correct application, checking that it is both the right application and associated with the logged in user. Use .first() to extract the first application that matches these requirements to avoid SQL returning a list
        if not a: # If a is empty, ie. the application could not be found for some reason, we return an error
            return jsonify({"error": "Application not found"}), 404

        deliverables = db.query(Deliverable).filter(Deliverable.application_id == app_id).all() # Grab all the deliverables associated with the application as a list
        deliv_texts = [f"-> {d.title} ({d.dtype}). Due: {d.due_date}. State: {d.state}." for d in deliverables] # List comprehension to format each deliverable to feed to Gemini
        deliv_str = "\n".join(deliv_texts) if deliv_texts else "No deliverables added yet." # Formats as one big strong to give to Gemini

        
        # Take the information in application, deliverables, and notes to build a system prompt that we can give to Gemini alongside the first chat. Essentially gives Gemini context without the user needing to tell it about the application
        # Use Persona, Task, Context, Format structure to build prompt
        system_instruction = f"""
        You are an expert interview prep assistant and career coach. Help the user prepare for their interview and hiring process by taking a look at the following notes/info.
        Here is the context of the job application:
        - Company: {a.company}
        - Role: {a.role}
        - Current Status: {a.status}
        - User's Notes on the job: {a.notes or 'None provided.'}
        
        Current Deliverables for this application:
        {deliv_str}

        Use this information to give tailored advice, mock interview questions, or next-step recommendations. Be concise, encouraging, and highly specific to the company and role provided. Utilize external research on the company and up to date interview/job search methods
        """

        formatted_history = [] # Define a formatted chat istory list, as this is how gemini takes input
        for msg in chat_history: # Parse each message in chat_history
            formatted_history.append( # Append the chat to the formatted_history list
                types.Content(role=msg["role"], # Content is a data structure the google.genai SDk uses to store content. We define role so Gemini knows who gave each response (user or model). chat_history is a list of dictionaries.
                              parts=[types.Part.from_text(text=msg["parts"])]) # Parts is a data structure under Content that allows you to build the Content data structure with text responses. from_text method allows you to pass text data from chat_history
            )
        
        chat = ai_client.chats.create( # Creates a new chat using the earlier define ai_client variable
            model="gemini-2.5-flash", # Selects the free model
            history=formatted_history, # Passes the formatted histroy we created
            config=types.GenerateContentConfig( # Allows us to pass our system prompt in a Content structure
                system_instruction=system_instruction,
            )
        )

        response = chat.send_message(user_message) # Send the new chat

        return jsonify({"reply": response.text}) # Package response as json data for the frontend to read
    
    except Exception as e: # If we get any errors, assign the Exception to the variable e
        return jsonify({"error": str(e)}), 500 # Package the exception for the frontend to display. Improvement would be to handle specific errors that are likely to occur for more precise debugging on the frontend
    finally: # Close the connection to the db either way so we don't crash anything
        db.close()
# -----------------------
# Deliverables
# -----------------------
@app.get("/applications/<int:app_id>/deliverables")
@jwt_required()
def list_deliverables(app_id: int):
    user_id = int(get_jwt_identity())


    db = SessionLocal()
    try:
        a = db.query(Application).filter(Application.id == app_id, Application.user_id == user_id).first()
        if not a:
            return jsonify({"error": "Not found"}), 404

        ds = db.query(Deliverable).filter(Deliverable.application_id == app_id).order_by(Deliverable.updated_at.desc()).all()
        return jsonify({"deliverables": [deliverable_to_dict(d) for d in ds]})
    finally:
        db.close()

@app.post("/applications/<int:app_id>/deliverables")
@jwt_required()
def create_deliverable(app_id: int):
    user_id = int(get_jwt_identity())

    data = request.get_json(force=True) or {}

    title = (data.get("title") or "").strip()
    dtype = (data.get("dtype") or "Other").strip()
    due_date = parse_iso_datetime(data.get("due_date"))
    state = (data.get("state") or "Not started").strip()
    content = data.get("content")
    is_done = bool(data.get("is_done", False))

    if not title:
        return jsonify({"error": "title is required"}), 400

    db = SessionLocal()
    try:
        a = db.query(Application).filter(Application.id == app_id, Application.user_id == user_id).first()
        if not a:
            return jsonify({"error": "Not found"}), 404

        d = Deliverable(
            application_id=app_id,
            title=title,
            dtype=dtype,
            due_date=due_date,
            state=state,
            content=content,
            is_done=is_done,
            updated_at=datetime.now(timezone.utc),
        )
        db.add(d)
        a.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(d)
        return jsonify({"deliverable": deliverable_to_dict(d)}), 201
    finally:
        db.close()

@app.put("/deliverables/<int:deliverable_id>")
@jwt_required()
def update_deliverable(deliverable_id: int):
    user_id = int(get_jwt_identity())

    data = request.get_json(force=True) or {}

    db = SessionLocal()
    try:
        d = (
            db.query(Deliverable)
            .join(Application, Deliverable.application_id == Application.id)
            .filter(Deliverable.id == deliverable_id, Application.user_id == user_id)
            .first()
        )
        if not d:
            return jsonify({"error": "Not found"}), 404

        if "title" in data:
            t = (data.get("title") or "").strip()
            if t:
                d.title = t
        if "dtype" in data:
            d.dtype = (data.get("dtype") or "Other").strip()
        if "due_date" in data:
            d.due_date = parse_iso_datetime(data.get("due_date"))
        if "state" in data:
            d.state = (data.get("state") or "").strip() or d.state
        if "content" in data:
            d.content = data.get("content")
        if "is_done" in data:
            d.is_done = bool(data.get("is_done"))
            if d.is_done:
                d.state = "Done"

        d.updated_at = datetime.now(timezone.utc)

        # bump parent updated_at
        parent = db.query(Application).filter(Application.id == d.application_id, Application.user_id == user_id).first()
        if parent:
            parent.updated_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(d)
        return jsonify({"deliverable": deliverable_to_dict(d)})
    finally:
        db.close()

@app.delete("/deliverables/<int:deliverable_id>")
@jwt_required()
def delete_deliverable(deliverable_id: int):
    user_id = int(get_jwt_identity())


    db = SessionLocal()
    try:
        d = (
            db.query(Deliverable)
            .join(Application, Deliverable.application_id == Application.id)
            .filter(Deliverable.id == deliverable_id, Application.user_id == user_id)
            .first()
        )
        if not d:
            return jsonify({"error": "Not found"}), 404

        parent_id = d.application_id
        db.delete(d)

        parent = db.query(Application).filter(Application.id == parent_id, Application.user_id == user_id).first()
        if parent:
            parent.updated_at = datetime.now(timezone.utc)

        db.commit()
        return jsonify({"deleted": True})
    finally:
        db.close()

# -----------------------
# Writing Bank
# -----------------------
@app.get("/writing")
@jwt_required()
def list_writing():
    user_id = int(get_jwt_identity())

    q = (request.args.get("q") or "").strip().lower()

    db = SessionLocal()
    try:
        query = db.query(WritingBankItem).filter(WritingBankItem.user_id == user_id)
        if q:
            like = f"%{q}%"
            query = query.filter(
                (WritingBankItem.title.ilike(like)) |
                (WritingBankItem.tags.ilike(like)) |
                (WritingBankItem.content.ilike(like))
            )
        items = query.order_by(WritingBankItem.updated_at.desc()).all()
        return jsonify({"items": [writing_item_to_dict(w) for w in items]})
    finally:
        db.close()

@app.post("/writing")
@jwt_required()
def create_writing():
    user_id = int(get_jwt_identity())

    data = request.get_json(force=True) or {}

    title = (data.get("title") or "").strip()
    tags = (data.get("tags") or "").strip() or None
    content = data.get("content") or ""

    if not title:
        return jsonify({"error": "title is required"}), 400
    if not content.strip():
        return jsonify({"error": "content is required"}), 400

    db = SessionLocal()
    try:
        w = WritingBankItem(
            user_id=user_id,
            title=title,
            tags=tags,
            content=content,
            updated_at=datetime.now(timezone.utc),
        )
        db.add(w)
        db.commit()
        db.refresh(w)
        return jsonify({"item": writing_item_to_dict(w)}), 201
    finally:
        db.close()

@app.put("/writing/<int:item_id>")
@jwt_required()
def update_writing(item_id: int):
    user_id = int(get_jwt_identity())

    data = request.get_json(force=True) or {}

    db = SessionLocal()
    try:
        w = db.query(WritingBankItem).filter(WritingBankItem.id == item_id, WritingBankItem.user_id == user_id).first()
        if not w:
            return jsonify({"error": "Not found"}), 404

        if "title" in data:
            t = (data.get("title") or "").strip()
            if t:
                w.title = t
        if "tags" in data:
            w.tags = (data.get("tags") or "").strip() or None
        if "content" in data:
            c = data.get("content") or ""
            if not c.strip():
                return jsonify({"error": "content cannot be empty"}), 400
            w.content = c

        w.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(w)
        return jsonify({"item": writing_item_to_dict(w)})
    finally:
        db.close()

@app.delete("/writing/<int:item_id>")
@jwt_required()
def delete_writing(item_id: int):
    user_id = int(get_jwt_identity())


    db = SessionLocal()
    try:
        w = db.query(WritingBankItem).filter(WritingBankItem.id == item_id, WritingBankItem.user_id == user_id).first()
        if not w:
            return jsonify({"error": "Not found"}), 404
        db.delete(w)
        db.commit()
        return jsonify({"deleted": True})
    finally:
        db.close()


if __name__ == "__main__":
    # local dev
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=True)
