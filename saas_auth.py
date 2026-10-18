"""
Authentication & Authorization Layer for Multi-Tenant Basketball Portrait Studio Pro
Password hashing, session tokens, and bulk user parsing.
"""

import re
import csv
import io
import hashlib
import secrets
from typing import Optional, Dict, Any, List
import saas_db


def hash_password(password: str, salt: str = None) -> tuple:
    """Hashes a password with PBKDF2-HMAC-SHA256 and returns (hex_hash, salt)."""
    if not salt:
        salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return key.hex(), salt


def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    """Securely verifies password against stored hash."""
    if not stored_hash or not salt:
        return False
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return secrets.compare_digest(key.hex(), stored_hash)


def generate_invite_token() -> str:
    """Generates a secure 32-byte URL-safe invite token."""
    return secrets.token_urlsafe(32)


def get_authenticated_user(headers) -> Optional[Dict[str, Any]]:
    """
    Extracts the authenticated user from the Authorization header or Cookie header.
    Returns the user dict with company information attached.
    """
    token = None
    auth_header = headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()

    if not token:
        cookie_header = headers.get("Cookie", "")
        if "session_token=" in cookie_header:
            m = re.search(r'session_token=([^;]+)', cookie_header)
            if m:
                token = m.group(1).strip()

    if not token:
        return None

    session = saas_db.get_session(token)
    if not session:
        return None

    user = saas_db.get_user_by_id(session["user_id"])
    if not user or not user.get("is_active"):
        return None

    company = saas_db.get_company_by_id(user["company_id"])
    user["company"] = company
    user["session_token"] = token
    return user


def parse_bulk_user_input(raw_text: str) -> List[Dict[str, str]]:
    """
    Parses a user-pasted block of text (CSV, TSV, or newline-separated).
    Supports formats:
      - email@example.com, John Doe, member
      - email@example.com, Jane Doe, company_admin
      - email@example.com
      - John Doe <email@example.com>
    """
    results = []
    seen = set()

    lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
    for line in lines:
        # Check format: "Full Name <email@example.com>"
        m = re.match(r'^([^<]+)<([^>]+)>', line)
        if m:
            name = m.group(1).strip()
            email = m.group(2).strip().lower()
            role = "member"
        else:
            parts = [p.strip() for p in re.split(r'[,;\t]', line)]
            email = parts[0].lower()
            name = parts[1] if len(parts) > 1 and parts[1] else email.split("@")[0].replace(".", " ").title()
            role = parts[2].lower() if len(parts) > 2 and parts[2] in ("company_admin", "admin", "member") else "member"
            if role == "admin":
                role = "company_admin"

        # Validate email
        if re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
            if email not in seen:
                seen.add(email)
                results.append({
                    "email": email,
                    "full_name": name,
                    "role": role
                })

    return results
