"""
Authentication & Authorization Layer for VeloRoster AI (Commercial Athletic Media & Roster Studio)
Developed from scratch with full proprietary rights by Ecstaticloud Technologies.
Commercial multi-tenant credentials, sessions, Passkeys (WebAuthn), and Two-Factor Authentication.
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


# --------------------------------------------------------------------------
# Multi-Factor Authentication (TOTP - RFC 6238)
# --------------------------------------------------------------------------

import base64
import hmac
import struct
import time
import json
import urllib.parse


def generate_totp_secret() -> str:
    """Generates a secure 160-bit (20 bytes) Base32 secret string for TOTP."""
    raw = secrets.token_bytes(20)
    return base64.b32encode(raw).decode("utf-8").rstrip("=")


def get_totp_uri(secret: str, email: str, issuer: str = "Sovereign Studio Pro") -> str:
    """Returns the standard otpauth:// URI for QR code generation."""
    label = f"{issuer}:{email}"
    params = {
        "secret": secret,
        "issuer": issuer,
        "algorithm": "SHA1",
        "digits": "6",
        "period": "30"
    }
    return f"otpauth://totp/{urllib.parse.quote(label)}?{urllib.parse.urlencode(params)}"


def generate_totp_code(secret: str, t: Optional[int] = None, time_step: int = 30) -> str:
    """Generates the 6-digit TOTP code for a given timestamp."""
    if t is None:
        t = int(time.time())
    counter = int(t // time_step)
    padded = secret + "=" * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(padded, casefold=True)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = (struct.unpack(">I", digest[offset:offset+4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{code_int:06d}"


def verify_totp_code(secret: str, code: str, window: int = 1, time_step: int = 30) -> bool:
    """Verifies a 6-digit TOTP code with time drift window tolerance."""
    if not secret or not code:
        return False
    curr = int(time.time())
    clean_code = str(code).strip().replace(" ", "")
    for w in range(-window, window + 1):
        expected = generate_totp_code(secret, curr + w * time_step, time_step)
        if secrets.compare_digest(expected, clean_code):
            return True
    return False


def generate_backup_codes(count: int = 8) -> List[str]:
    """Generates human-readable 8-character single-use emergency backup codes."""
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    codes = []
    for _ in range(count):
        p1 = "".join(secrets.choice(chars) for _ in range(4))
        p2 = "".join(secrets.choice(chars) for _ in range(4))
        codes.append(f"{p1}-{p2}")
    return codes


def verify_and_consume_backup_code(user_id: str, code: str) -> bool:
    """Verifies and consumes a single-use backup code for a user."""
    user = saas_db.get_user_by_id(user_id)
    if not user or not user.get("mfa_backup_codes"):
        return False
    try:
        codes = json.loads(user["mfa_backup_codes"])
    except Exception:
        return False

    clean_code = str(code).strip().upper().replace(" ", "").replace("-", "")
    for idx, c in enumerate(codes):
        if c.replace("-", "").upper() == clean_code:
            codes.pop(idx)
            saas_db.execute_query(
                "UPDATE users SET mfa_backup_codes = ? WHERE id = ?",
                (json.dumps(codes), user_id),
                commit=True
            )
            return True
    return False


# --------------------------------------------------------------------------
# Temporary MFA Login Session Store
# --------------------------------------------------------------------------

_MFA_LOGIN_TOKENS: Dict[str, Dict[str, Any]] = {}


def create_mfa_login_token(user_id: str, ttl_seconds: int = 300) -> str:
    """Creates a temporary MFA challenge token expiring in 5 minutes."""
    tok = secrets.token_urlsafe(32)
    _clean_expired_mfa_tokens()
    _MFA_LOGIN_TOKENS[tok] = {
        "user_id": user_id,
        "expires_at": time.time() + ttl_seconds
    }
    return tok


def verify_mfa_login_token(tok: str) -> Optional[str]:
    """Returns user_id if token is valid, and consumes the token."""
    _clean_expired_mfa_tokens()
    data = _MFA_LOGIN_TOKENS.pop(tok, None)
    if not data or time.time() > data["expires_at"]:
        return None
    return data["user_id"]


def _clean_expired_mfa_tokens():
    now = time.time()
    expired = [k for k, v in _MFA_LOGIN_TOKENS.items() if now > v["expires_at"]]
    for k in expired:
        _MFA_LOGIN_TOKENS.pop(k, None)


# --------------------------------------------------------------------------
# Passkey (WebAuthn / FIDO2) Challenge Management
# --------------------------------------------------------------------------

_WEBAUTHN_CHALLENGES: Dict[str, Dict[str, Any]] = {}


def create_passkey_register_challenge(user: Dict[str, Any], ttl_seconds: int = 180) -> Dict[str, Any]:
    challenge = secrets.token_urlsafe(32)
    now = time.time()
    _clean_webauthn_challenges()
    challenge_id = secrets.token_hex(16)
    _WEBAUTHN_CHALLENGES[challenge_id] = {
        "user_id": user["id"],
        "challenge": challenge,
        "type": "register",
        "expires_at": now + ttl_seconds
    }
    return {
        "challenge_id": challenge_id,
        "challenge": challenge,
        "rp": {
            "name": "Sovereign Studio Pro"
        },
        "user": {
            "id": user["id"],
            "name": user["email"],
            "displayName": user["full_name"]
        },
        "pubKeyCredParams": [
            {"type": "public-key", "alg": -7},   # ES256
            {"type": "public-key", "alg": -257}  # RS256
        ],
        "timeout": 60000,
        "attestation": "none"
    }


def create_passkey_login_challenge(ttl_seconds: int = 180) -> Dict[str, Any]:
    challenge = secrets.token_urlsafe(32)
    now = time.time()
    _clean_webauthn_challenges()
    challenge_id = secrets.token_hex(16)
    _WEBAUTHN_CHALLENGES[challenge_id] = {
        "challenge": challenge,
        "type": "login",
        "expires_at": now + ttl_seconds
    }
    return {
        "challenge_id": challenge_id,
        "challenge": challenge,
        "timeout": 60000,
        "userVerification": "preferred"
    }


def verify_passkey_challenge(challenge_id: str, expected_type: str = None) -> Optional[Dict[str, Any]]:
    _clean_webauthn_challenges()
    data = _WEBAUTHN_CHALLENGES.pop(challenge_id, None)
    if not data or time.time() > data["expires_at"]:
        return None
    if expected_type and data.get("type") != expected_type:
        return None
    return data


def _clean_webauthn_challenges():
    now = time.time()
    expired = [k for k, v in _WEBAUTHN_CHALLENGES.items() if now > v["expires_at"]]
    for k in expired:
        _WEBAUTHN_CHALLENGES.pop(k, None)

