"""
Multi-Tenant Database Engine for VeloRoster AI (Commercial Athletic Media & Roster Studio)
Developed from scratch with full proprietary rights by Ecstaticloud Technologies.
Commercial PostgreSQL / SQLite storage for organizations, licensed seats, and sports assets.
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


def get_sqlite_path() -> str:
    """Returns the resolved SQLite database file path, honoring persistent disk mounts."""
    # Check for Render persistent disk or custom data directory
    data_dir = os.environ.get("DATA_DIR") or os.environ.get("RENDER_DISK_PATH")
    if data_dir and os.path.isdir(data_dir):
        return os.path.join(data_dir, "studio_saas.db")
    if os.environ.get("SQLITE_DB_PATH"):
        return os.environ.get("SQLITE_DB_PATH")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "studio_saas.db")


def get_connection():
    """Returns an active database connection (PostgreSQL or SQLite)."""
    if IS_POSTGRES:
        try:
            import psycopg2
            db_url = DATABASE_URL
            if "sslmode=" not in db_url and "localhost" not in db_url and "127.0.0.1" not in db_url:
                db_url += ("&" if "?" in db_url else "?") + "sslmode=require"
            return psycopg2.connect(db_url)
        except Exception as e_psycopg2:
            try:
                import pg8000.dbapi
                import ssl
                parsed = urllib.parse.urlparse(DATABASE_URL)
                ssl_ctx = ssl.create_default_context()
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl.CERT_NONE
                return pg8000.dbapi.connect(
                    user=parsed.username,
                    password=parsed.password,
                    host=parsed.hostname,
                    port=parsed.port or 5432,
                    database=parsed.path.lstrip("/").split("?")[0],
                    ssl_context=ssl_ctx
                )
            except Exception as e_pg8000:
                print(f"[SaaS DB Warning] Failed to connect to PostgreSQL (psycopg2: {e_psycopg2}, pg8000: {e_pg8000}), falling back to SQLite.")

    # SQLite fallback (with persistent disk detection)
    import sqlite3
    db_path = get_sqlite_path()
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
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

        # 4. Passkeys Table (WebAuthn / FIDO2)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS passkeys (
                id VARCHAR(36) PRIMARY KEY,
                user_id VARCHAR(36) NOT NULL,
                credential_id TEXT UNIQUE NOT NULL,
                public_key TEXT,
                name VARCHAR(255) NOT NULL,
                counter INTEGER DEFAULT 0,
                created_at VARCHAR(50) NOT NULL,
                last_used_at VARCHAR(50)
            )
        """)

        # Alter users table to add MFA fields if missing
        for col_def in [
            "mfa_enabled INTEGER DEFAULT 0",
            "mfa_secret VARCHAR(64)",
            "mfa_backup_codes TEXT"
        ]:
            try:
                cur.execute(f"ALTER TABLE users ADD COLUMN {col_def}")
            except Exception:
                pass

        conn.commit()
    finally:
        cur.close()
        conn.close()

    # Diagnostic storage logging
    if IS_POSTGRES:
        print("[SaaS DB] Database engine: PostgreSQL (Persistent storage across all cloud deploys & restarts).")
    elif os.environ.get("DATA_DIR") or os.environ.get("RENDER_DISK_PATH") or os.environ.get("SQLITE_DB_PATH"):
        print(f"[SaaS DB] Database engine: SQLite Persistent Disk at: {get_sqlite_path()}")
    else:
        print(f"[SaaS DB Notice] Database engine: Local SQLite ({get_sqlite_path()}).")
        if os.environ.get("RENDER"):
            print("[SaaS DB Warning] Ephemeral Render storage detected! Set DATABASE_URL or attach a Persistent Disk to prevent data reset on service restart.")

    # Seed default platform admin and demo organization if DB is empty
    _seed_defaults()


def _seed_defaults():
    """Seeds initial platform admin and default sports organization if database is clean."""
    import hashlib

    # Allow custom SuperAdmin credentials from environment variables (essential for Render / Cloud deployments)
    super_email = (os.environ.get("SUPERADMIN_EMAIL") or "admin@athletics.com").strip().lower()
    super_pass = os.environ.get("SUPERADMIN_PASSWORD") or "admin"
    super_name = (os.environ.get("SUPERADMIN_NAME") or "Platform Administrator").strip()

    companies = execute_query("SELECT id FROM companies LIMIT 1")
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    if not companies:
        company_id = str(uuid.uuid4())
        admin_id = str(uuid.uuid4())

        # Create default demo company
        execute_query("""
            INSERT INTO companies (id, name, slug, plan, max_seats, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (company_id, "Athletics Media Group", "athletics-media", "team", 15, "active", now), commit=True)

        salt = "4f8a1290bcde5678"
        p_hash = hashlib.pbkdf2_hmac("sha256", super_pass.encode("utf-8"), salt.encode("utf-8"), 100_000).hex()

        # Create SuperAdmin user
        execute_query("""
            INSERT INTO users (id, company_id, email, password_hash, salt, full_name, role, is_active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
        """, (admin_id, company_id, super_email, p_hash, salt, super_name, "superadmin", now), commit=True)

        print(f"[SaaS DB] Initialized demo company 'Athletics Media Group' with superadmin '{super_email}'")
    else:
        # Ensure the configured superadmin exists
        target_super = execute_query("SELECT id, email, role FROM users WHERE LOWER(email) = ?", (super_email,))
        first_company_id = companies[0]["id"]
        salt = "4f8a1290bcde5678"
        p_hash = hashlib.pbkdf2_hmac("sha256", super_pass.encode("utf-8"), salt.encode("utf-8"), 100_000).hex()

        if not target_super:
            admin_id = str(uuid.uuid4())
            execute_query("""
                INSERT INTO users (id, company_id, email, password_hash, salt, full_name, role, is_active, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
            """, (admin_id, first_company_id, super_email, p_hash, salt, super_name, "superadmin", now), commit=True)
            print(f"[SaaS DB] Created platform superadmin '{super_email}'")
        elif os.environ.get("SUPERADMIN_PASSWORD"):
            execute_query("""
                UPDATE users SET password_hash = ?, salt = ?, is_active = 1 WHERE role = 'superadmin'
            """, (p_hash, salt), commit=True)


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
    rows = execute_query(
        "SELECT COUNT(*) as count FROM users WHERE company_id = ? AND is_active = 1 AND (role IS NULL OR role != 'superadmin')",
        (company_id,)
    )
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


# --------------------------------------------------------------------------
# User Credentials & MFA Management
# --------------------------------------------------------------------------

def update_user_credentials(user_id: str, email: str = None, full_name: str = None, password_hash: str = None, salt: str = None) -> Optional[Dict[str, Any]]:
    updates = []
    params = []
    if email:
        updates.append("email = ?")
        params.append(email.strip().lower())
    if full_name:
        updates.append("full_name = ?")
        params.append(full_name.strip())
    if password_hash and salt:
        updates.append("password_hash = ?")
        params.append(password_hash)
        updates.append("salt = ?")
        params.append(salt)
    if not updates:
        return get_user_by_id(user_id)
    params.append(user_id)
    execute_query(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", tuple(params), commit=True)
    return get_user_by_id(user_id)


def update_user_mfa(user_id: str, enabled: bool, secret: str = None, backup_codes_json: str = None):
    execute_query(
        "UPDATE users SET mfa_enabled = ?, mfa_secret = ?, mfa_backup_codes = ? WHERE id = ?",
        (1 if enabled else 0, secret, backup_codes_json, user_id),
        commit=True
    )


# --------------------------------------------------------------------------
# Passkey (WebAuthn / FIDO2) Methods
# --------------------------------------------------------------------------

def create_passkey(user_id: str, credential_id: str, public_key: str, name: str) -> Dict[str, Any]:
    passkey_id = str(uuid.uuid4())
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    execute_query("""
        INSERT INTO passkeys (id, user_id, credential_id, public_key, name, counter, created_at, last_used_at)
        VALUES (?, ?, ?, ?, ?, 0, ?, ?)
    """, (passkey_id, user_id, credential_id, public_key, name.strip() or "Biometric Key", now, now), commit=True)
    return get_passkey_by_id(passkey_id)


def get_passkey_by_id(passkey_id: str) -> Optional[Dict[str, Any]]:
    rows = execute_query("SELECT * FROM passkeys WHERE id = ?", (passkey_id,))
    return rows[0] if rows else None


def get_passkey_by_credential_id(credential_id: str) -> Optional[Dict[str, Any]]:
    rows = execute_query("SELECT * FROM passkeys WHERE credential_id = ?", (credential_id.strip(),))
    return rows[0] if rows else None


def get_passkeys_by_user(user_id: str) -> List[Dict[str, Any]]:
    return execute_query("SELECT id, user_id, credential_id, name, counter, created_at, last_used_at FROM passkeys WHERE user_id = ? ORDER BY created_at DESC", (user_id,))


def update_passkey_usage(credential_id: str, counter: int = None):
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if counter is not None:
        execute_query("UPDATE passkeys SET counter = ?, last_used_at = ? WHERE credential_id = ?", (counter, now, credential_id), commit=True)
    else:
        execute_query("UPDATE passkeys SET last_used_at = ? WHERE credential_id = ?", (now, credential_id), commit=True)


def delete_passkey(passkey_id: str, user_id: str) -> bool:
    execute_query("DELETE FROM passkeys WHERE id = ? AND user_id = ?", (passkey_id, user_id), commit=True)
    return True


# --------------------------------------------------------------------------
# Platform Overview Metrics for SuperAdmin Dashboard
# --------------------------------------------------------------------------

def get_platform_metrics() -> Dict[str, Any]:
    companies = get_all_companies()
    total_companies = len(companies)
    total_seats = sum(c.get("max_seats", 0) for c in companies)
    total_used_seats = sum(c.get("used_seats", 0) for c in companies)

    users = execute_query("SELECT id, company_id, email, full_name, role, is_active FROM users")
    total_users = len(users)
    superadmins = [u for u in users if u.get("role") == "superadmin"]
    regular_members = [u for u in users if u.get("role") != "superadmin"]

    plans = {"free": 0, "team": 0, "enterprise": 0}
    for c in companies:
        p = (c.get("plan") or "team").lower()
        plans[p] = plans.get(p, 0) + 1

    return {
        "total_companies": total_companies,
        "total_seats_allocated": total_seats,
        "total_used_seats": total_used_seats,
        "total_users": total_users,
        "superadmin_count": len(superadmins),
        "regular_member_count": len(regular_members),
        "plans_breakdown": plans,
        "companies": companies
    }

