"""
Multi-Tenant SaaS Database Layer for Basketball Portrait Studio Pro
Supports PostgreSQL (Production/Cloud via DATABASE_URL) and SQLite (Local Fallback).
"""

import os
import sys
import uuid
import datetime
import urllib.parse
from typing import Optional, List, Dict, Any

# Detect database configuration
DATABASE_URL = os.environ.get("DATABASE_URL")
IS_POSTGRES = bool(DATABASE_URL and DATABASE_URL.startswith(("postgres://", "postgresql://")))

if IS_POSTGRES and DATABASE_URL.startswith("postgres://"):
    # Fix Render/Heroku legacy postgres:// to postgresql://
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)


def get_connection():
    """Returns an active database connection (PostgreSQL or SQLite)."""
    if IS_POSTGRES:
        try:
            import psycopg2
            return psycopg2.connect(DATABASE_URL)
        except Exception:
            try:
                import pg8000.dbapi
                parsed = urllib.parse.urlparse(DATABASE_URL)
                return pg8000.dbapi.connect(
                    user=parsed.username,
                    password=parsed.password,
                    host=parsed.hostname,
                    port=parsed.port or 5432,
                    database=parsed.path.lstrip("/")
                )
            except Exception as e:
                print(f"[SaaS DB Warning] Failed to connect to PostgreSQL ({e}), falling back to SQLite.")

    # SQLite fallback
    import sqlite3
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "studio_saas.db")
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def adapt_query(query: str, is_pg: bool) -> str:
    """Converts standard ? parameter placeholders to %s for PostgreSQL."""
    if is_pg:
        return query.replace("?", "%s")
    return query


def execute_query(query: str, params: tuple = (), commit: bool = False) -> List[Dict[str, Any]]:
    """Executes a query and returns rows as dictionaries."""
    conn = get_connection()
    is_pg = hasattr(conn, "server_version") or "pg8000" in conn.__class__.__module__
    q = adapt_query(query, is_pg)

    try:
        cur = conn.cursor()
        cur.execute(q, params)
        if commit:
            conn.commit()

        if cur.description:
            col_names = [d[0] for d in cur.description]
            rows = cur.fetchall()
            result = [dict(zip(col_names, row)) for row in rows]
        else:
            result = []
        cur.close()
        return result
    except Exception as e:
        if commit:
            try:
                conn.rollback()
            except Exception:
                pass
        raise e
    finally:
        conn.close()


def init_db():
    """Initializes schema tables and default seed data if empty."""
    conn = get_connection()
    is_pg = hasattr(conn, "server_version") or "pg8000" in conn.__class__.__module__
    cur = conn.cursor()

    try:
        # 1. Companies / Organizations Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS companies (
                id VARCHAR(36) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                slug VARCHAR(100) UNIQUE NOT NULL,
                plan VARCHAR(50) DEFAULT 'team',
                max_seats INTEGER DEFAULT 10,
                status VARCHAR(50) DEFAULT 'active',
                created_at VARCHAR(50) NOT NULL,
                expires_at VARCHAR(50)
            )
        """)

        # 2. Users Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id VARCHAR(36) PRIMARY KEY,
                company_id VARCHAR(36) NOT NULL,
                email VARCHAR(255) UNIQUE NOT NULL,
                password_hash VARCHAR(255),
                salt VARCHAR(64),
                full_name VARCHAR(255) NOT NULL,
                role VARCHAR(50) DEFAULT 'member',
                is_active INTEGER DEFAULT 1,
                invite_token VARCHAR(128),
                invite_expires_at VARCHAR(50),
                created_at VARCHAR(50) NOT NULL
            )
        """)

        # 3. User Sessions Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                token VARCHAR(128) PRIMARY KEY,
                user_id VARCHAR(36) NOT NULL,
                expires_at VARCHAR(50) NOT NULL,
                created_at VARCHAR(50) NOT NULL
            )
        """)

        conn.commit()
    finally:
        cur.close()
        conn.close()

    # Seed default platform admin and demo organization if DB is empty
    _seed_defaults()


def _seed_defaults():
    """Seeds initial platform admin and default sports organization if database is clean."""
    companies = execute_query("SELECT id FROM companies LIMIT 1")
    if companies:
        return

    import hashlib
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    company_id = str(uuid.uuid4())
    admin_id = str(uuid.uuid4())

    # Create default demo company
    execute_query("""
        INSERT INTO companies (id, name, slug, plan, max_seats, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (company_id, "Athletics Media Group", "athletics-media", "team", 15, "active", now), commit=True)

    # Hash default password: "admin"
    salt = "4f8a1290bcde5678"
    p_hash = hashlib.pbkdf2_hmac("sha256", "admin".encode("utf-8"), salt.encode("utf-8"), 100_000).hex()

    # Create SuperAdmin user
    execute_query("""
        INSERT INTO users (id, company_id, email, password_hash, salt, full_name, role, is_active, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
    """, (admin_id, company_id, "admin@athletics.com", p_hash, salt, "Platform Administrator", "superadmin", now), commit=True)

    print(f"[SaaS DB] Seeded default company 'Athletics Media Group' with superadmin 'admin@athletics.com' (password: admin)")


# --------------------------------------------------------------------------
# Company / Organization Methods
# --------------------------------------------------------------------------

def get_company_by_id(company_id: str) -> Optional[Dict[str, Any]]:
    rows = execute_query("SELECT * FROM companies WHERE id = ?", (company_id,))
    return rows[0] if rows else None


def get_company_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    rows = execute_query("SELECT * FROM companies WHERE slug = ?", (slug.lower().strip(),))
    return rows[0] if rows else None


def get_all_companies() -> List[Dict[str, Any]]:
    rows = execute_query("SELECT * FROM companies ORDER BY created_at DESC")
    for r in rows:
        r["used_seats"] = get_company_seat_count(r["id"])
    return rows


def create_company(name: str, plan: str = "team", max_seats: int = 10, expires_at: str = None) -> Dict[str, Any]:
    company_id = str(uuid.uuid4())
    base_slug = "".join(c for c in name.lower().replace(" ", "-") if c.isalnum() or c == "-") or "company"
    slug = base_slug
    counter = 2
    while get_company_by_slug(slug):
        slug = f"{base_slug}-{counter}"
        counter += 1

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    execute_query("""
        INSERT INTO companies (id, name, slug, plan, max_seats, status, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?, 'active', ?, ?)
    """, (company_id, name.strip(), slug, plan, max_seats, now, expires_at), commit=True)

    return get_company_by_id(company_id)


def update_company_plan(company_id: str, plan: str, max_seats: int, status: str = "active") -> Optional[Dict[str, Any]]:
    execute_query("""
        UPDATE companies SET plan = ?, max_seats = ?, status = ? WHERE id = ?
    """, (plan, max_seats, status, company_id), commit=True)
    return get_company_by_id(company_id)


def get_company_seat_count(company_id: str) -> int:
    rows = execute_query("SELECT COUNT(*) as count FROM users WHERE company_id = ? AND is_active = 1", (company_id,))
    return rows[0]["count"] if rows else 0


# --------------------------------------------------------------------------
# User Methods
# --------------------------------------------------------------------------

def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    rows = execute_query("SELECT * FROM users WHERE id = ?", (user_id,))
    return rows[0] if rows else None


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    rows = execute_query("SELECT * FROM users WHERE LOWER(email) = LOWER(?)", (email.strip(),))
    return rows[0] if rows else None


def get_user_by_invite_token(token: str) -> Optional[Dict[str, Any]]:
    rows = execute_query("SELECT * FROM users WHERE invite_token = ?", (token.strip(),))
    return rows[0] if rows else None


def get_users_by_company(company_id: str) -> List[Dict[str, Any]]:
    return execute_query("SELECT id, company_id, email, full_name, role, is_active, invite_token, created_at FROM users WHERE company_id = ? ORDER BY created_at ASC", (company_id,))


def create_user(company_id: str, email: str, full_name: str, role: str = "member", invite_token: str = None) -> Dict[str, Any]:
    user_id = str(uuid.uuid4())
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    expires_at = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=7)).isoformat() if invite_token else None

    execute_query("""
        INSERT INTO users (id, company_id, email, full_name, role, is_active, invite_token, invite_expires_at, created_at)
        VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
    """, (user_id, company_id, email.strip().lower(), full_name.strip(), role, invite_token, expires_at, now), commit=True)

    return get_user_by_id(user_id)


def activate_user(user_id: str, password_hash: str, salt: str, full_name: str = None):
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if full_name:
        execute_query("""
            UPDATE users SET password_hash = ?, salt = ?, full_name = ?, invite_token = NULL, invite_expires_at = NULL, is_active = 1 WHERE id = ?
        """, (password_hash, salt, full_name.strip(), user_id), commit=True)
    else:
        execute_query("""
            UPDATE users SET password_hash = ?, salt = ?, invite_token = NULL, invite_expires_at = NULL, is_active = 1 WHERE id = ?
        """, (password_hash, salt, user_id), commit=True)


def update_user_status(user_id: str, is_active: bool):
    execute_query("UPDATE users SET is_active = ? WHERE id = ?", (1 if is_active else 0, user_id), commit=True)


def update_user_role(user_id: str, role: str):
    execute_query("UPDATE users SET role = ? WHERE id = ?", (role, user_id), commit=True)


def delete_user(user_id: str):
    execute_query("DELETE FROM sessions WHERE user_id = ?", (user_id,), commit=True)
    execute_query("DELETE FROM users WHERE id = ?", (user_id,), commit=True)


# --------------------------------------------------------------------------
# Session Methods
# --------------------------------------------------------------------------

def create_session(user_id: str, days: int = 30) -> str:
    token = uuid.uuid4().hex + uuid.uuid4().hex
    now = datetime.datetime.now(datetime.timezone.utc)
    expires = (now + datetime.timedelta(days=days)).isoformat()
    execute_query("""
        INSERT INTO sessions (token, user_id, expires_at, created_at)
        VALUES (?, ?, ?, ?)
    """, (token, user_id, expires, now.isoformat()), commit=True)
    return token


def get_session(token: str) -> Optional[Dict[str, Any]]:
    rows = execute_query("SELECT * FROM sessions WHERE token = ?", (token,))
    if not rows:
        return None
    session = rows[0]
    try:
        exp = datetime.datetime.fromisoformat(session["expires_at"])
        if datetime.datetime.now(datetime.timezone.utc) > exp:
            delete_session(token)
            return None
    except Exception:
        pass
    return session


def delete_session(token: str):
    execute_query("DELETE FROM sessions WHERE token = ?", (token,), commit=True)
