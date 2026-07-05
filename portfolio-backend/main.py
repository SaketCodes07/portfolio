"""
Portfolio contact-form backend.

Replaces the Google Apps Script endpoint used in hire.html with a small
FastAPI service that:
  - accepts the same form fields the frontend already sends
  - stores every submission in a local SQLite database
  - emails you a notification (optional — skipped if SMTP env vars are blank)
  - exposes a simple admin endpoint to view stored messages
"""

import os
import sqlite3
import smtplib
from datetime import datetime, timezone
from email.mime.text import MIMEText
from contextlib import contextmanager

from fastapi import FastAPI, Form, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from dotenv import load_dotenv

load_dotenv()  # reads variables from a local .env file if present

DB_PATH = os.getenv("DB_PATH", "contact.db")
ADMIN_KEY = os.getenv("ADMIN_KEY", "")

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL", "")

# Comma-separated list of origins allowed to call this API, e.g.
# "https://saketsaurabh07.github.io,https://saketsaurabh.dev"
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",")]

app = FastAPI(title="Saket Saurabh — Portfolio Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                about TEXT,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


@app.on_event("startup")
def on_startup():
    init_db()


def send_notification_email(name: str, email: str, about: str, message: str) -> None:
    """Best-effort email notification. Silently skipped if SMTP isn't configured,
    and never raises — a failed email should never break the contact form."""
    if not (SMTP_HOST and SMTP_USER and SMTP_PASS and NOTIFY_EMAIL):
        return
    try:
        body = f"From: {name} <{email}>\nAbout: {about}\n\n{message}"
        msg = MIMEText(body)
        msg["Subject"] = f"Portfolio contact: {name}"
        msg["From"] = SMTP_USER
        msg["To"] = NOTIFY_EMAIL

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
    except Exception as exc:  # noqa: BLE001 — deliberately broad, this is best-effort
        print(f"[warn] failed to send notification email: {exc}")


@app.post("/api/contact", response_class=PlainTextResponse)
def submit_contact(
    name: str = Form(...),
    email: str = Form(...),
    about: str = Form(...),
    message: str = Form(...),
):
    name, email, about, message = name.strip(), email.strip(), about.strip(), message.strip()

    if not name or not email or not message:
        raise HTTPException(status_code=400, detail="Name, email, and message are required.")
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Please provide a valid email address.")

    with get_db() as conn:
        conn.execute(
            "INSERT INTO messages (name, email, about, message, created_at) VALUES (?, ?, ?, ?, ?)",
            (name, email, about, message, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()

    send_notification_email(name, email, about, message)

    # Plain-text response — matches what hire.html already expects and displays.
    return f"Thanks {name}! Your message has been received — I'll get back to you soon."


@app.get("/api/messages")
def list_messages(x_admin_key: str = Header(default="")):
    if not ADMIN_KEY or x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, name, email, about, message, created_at FROM messages ORDER BY id DESC"
        ).fetchall()

    return [
        {
            "id": r[0],
            "name": r[1],
            "email": r[2],
            "about": r[3],
            "message": r[4],
            "created_at": r[5],
        }
        for r in rows
    ]


@app.get("/api/health")
def health():
    return {"status": "ok"}
