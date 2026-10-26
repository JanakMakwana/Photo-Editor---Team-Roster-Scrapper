"""
Authentication, Session, MFA, and Passkey WebAuthn API endpoints.
"""

from typing import Optional, Dict, Any
from fastapi import APIRouter, Request, Response, HTTPException, status, Depends
from pydantic import BaseModel
import saas_auth
import saas_db
from backend.core.rbac import get_current_user, require_auth

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


class LoginRequest(BaseModel):
    email: str
    password: str


class ActivateRequest(BaseModel):
    invite_token: str
    password: str
    full_name: Optional[str] = None


class MfaVerifyRequest(BaseModel):
    temp_token: str
    code: str


class UpdateCredentialsRequest(BaseModel):
    email: Optional[str] = None
    full_name: Optional[str] = None
    current_password: Optional[str] = None
    new_password: Optional[str] = None


def _format_user_payload(user: Dict[str, Any]) -> Dict[str, Any]:
    """Formats safe user object for frontend consumption."""
    is_superadmin = (user.get("role") == "superadmin")
    company = user.get("company") if not is_superadmin else None
    used_seats = saas_db.get_company_seat_count(user["company_id"]) if (user.get("company_id") and not is_superadmin) else 0
    passkeys = saas_db.get_passkeys_by_user(user["id"])
    platform_metrics = saas_db.get_platform_metrics() if is_superadmin else None

    return {
        "id": user["id"],
        "company_id": None if is_superadmin else user.get("company_id"),
        "email": user["email"],
        "full_name": user["full_name"],
        "role": user["role"],
        "is_superadmin": is_superadmin,
        "mfa_enabled": bool(user.get("mfa_enabled")),
        "passkeys_count": len(passkeys),
        "platform_metrics": platform_metrics,
        "is_active": user["is_active"],
        "created_at": user.get("created_at"),
        "company": {
            "id": company["id"],
            "name": company["name"],
            "slug": company["slug"],
            "plan": company.get("plan", "team"),
            "max_seats": company.get("max_seats", 10),
            "used_seats": used_seats,
            "remaining_seats": max(0, company.get("max_seats", 10) - used_seats),
            "status": company.get("status", "active")
        } if company else None
    }


@router.post("/login")
async def login(req: LoginRequest, response: Response):
    user = saas_db.get_user_by_email(req.email)
    if not user or not user.get("is_active"):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    if not saas_auth.verify_password(req.password, user.get("password_hash"), user.get("salt")):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    # Check if MFA is enabled
    if user.get("mfa_enabled") and user.get("mfa_secret"):
        temp_token = saas_auth.generate_invite_token()
        # Save temp session for MFA validation
        saas_db.create_session(user["id"], days=1)
        return {"status": "mfa_required", "temp_token": temp_token, "user_id": user["id"]}

    token = saas_db.create_session(user["id"])
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=30 * 86400,
        path="/"
    )

    company = saas_db.get_company_by_id(user["company_id"])
    user["company"] = company
    user["session_token"] = token

    return {
        "status": "ok",
        "token": token,
        "user": _format_user_payload(user)
    }


@router.get("/me")
async def get_me(user: Optional[Dict[str, Any]] = Depends(get_current_user)):
    if not user:
        return {"logged_in": False, "user": None}
    return {
        "logged_in": True,
        "user": _format_user_payload(user)
    }


@router.post("/logout")
async def logout(request: Request, response: Response):
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip() if auth_header.startswith("Bearer ") else request.cookies.get("session_token")
    if token:
        saas_db.delete_session(token)
    response.delete_cookie(key="session_token", path="/")
    return {"status": "ok", "message": "Signed out successfully."}


@router.post("/activate")
async def activate_account(req: ActivateRequest, response: Response):
    user = saas_db.get_user_by_invite_token(req.invite_token)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired invitation token.")

    p_hash, salt = saas_auth.hash_password(req.password)
    saas_db.activate_user(user["id"], p_hash, salt, full_name=req.full_name)

    token = saas_db.create_session(user["id"])
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=30 * 86400,
        path="/"
    )

    activated_user = saas_db.get_user_by_id(user["id"])
    company = saas_db.get_company_by_id(activated_user["company_id"])
    activated_user["company"] = company
    activated_user["session_token"] = token

    return {
        "status": "ok",
        "message": "Account activated successfully.",
        "token": token,
        "user": _format_user_payload(activated_user)
    }


@router.post("/mfa/verify_login")
async def verify_mfa_login(req: MfaVerifyRequest, response: Response):
    user_id = req.temp_token.split(":")[0] if ":" in req.temp_token else None
    # Support direct user id or token
    user = saas_db.get_user_by_id(user_id) if user_id else None
    if not user:
        # Fallback to checking active session
        session = saas_db.get_session(req.temp_token)
        if session:
            user = saas_db.get_user_by_id(session["user_id"])

    if not user or not user.get("mfa_secret"):
        raise HTTPException(status_code=400, detail="Invalid verification request.")

    code = req.code.strip().replace(" ", "")
    valid = saas_auth.verify_totp_code(user["mfa_secret"], code)
    if not valid:
        # Check backup code
        backup_codes_str = user.get("mfa_backup_codes")
        if backup_codes_str:
            import json
            try:
                backup_codes = json.loads(backup_codes_str)
                if code in backup_codes:
                    backup_codes.remove(code)
                    saas_db.update_user_mfa(user["id"], enabled=True, secret=user["mfa_secret"], backup_codes_json=json.dumps(backup_codes))
                    valid = True
            except Exception:
                pass

    if not valid:
        raise HTTPException(status_code=401, detail="Invalid authenticator code.")

    token = saas_db.create_session(user["id"])
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=30 * 86400,
        path="/"
    )

    company = saas_db.get_company_by_id(user["company_id"])
    user["company"] = company
    user["session_token"] = token

    return {
        "status": "ok",
        "token": token,
        "user": _format_user_payload(user)
    }


@router.post("/passkey/login_options")
async def passkey_login_options():
    opts = saas_auth.create_passkey_login_challenge()
    return {"status": "ok", "options": opts}


@router.post("/passkey/login_verify")
async def passkey_login_verify(payload: Dict[str, Any], response: Response):
    cred_id = payload.get("id") or payload.get("credentialId")
    if not cred_id:
        raise HTTPException(status_code=400, detail="Missing credential ID.")

    pk = saas_db.get_passkey_by_credential_id(cred_id)
    if not pk:
        raise HTTPException(status_code=401, detail="Unrecognized biometric passkey.")

    user = saas_db.get_user_by_id(pk["user_id"])
    if not user or not user.get("is_active"):
        raise HTTPException(status_code=403, detail="Account is disabled or inactive.")

    saas_db.update_passkey_usage(pk["credential_id"])
    token = saas_db.create_session(user["id"])
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=30 * 86400,
        path="/"
    )

    company = saas_db.get_company_by_id(user["company_id"])
    user["company"] = company
    user["session_token"] = token

    return {
        "status": "ok",
        "token": token,
        "user": _format_user_payload(user)
    }


@router.get("/passkey/list")
async def passkey_list(user: Dict[str, Any] = Depends(require_auth)):
    keys = saas_db.get_passkeys_by_user(user["id"])
    return {
        "status": "ok",
        "passkeys": [
            {
                "id": k["id"],
                "credential_id": k["credential_id"],
                "name": k.get("name") or "Biometric Key",
                "created_at": k.get("created_at"),
                "last_used_at": k.get("last_used_at")
            }
            for k in keys
        ]
    }


@router.post("/passkey/register_options")
async def passkey_register_options(user: Dict[str, Any] = Depends(require_auth)):
    opts = saas_auth.create_passkey_register_challenge(user)
    return {"status": "ok", "options": opts}


@router.post("/passkey/register_verify")
async def passkey_register_verify(payload: Dict[str, Any], user: Dict[str, Any] = Depends(require_auth)):
    cred_id = payload.get("id") or payload.get("credentialId")
    raw_id = payload.get("rawId") or cred_id
    key_name = payload.get("name") or "Passkey"
    if not cred_id:
        raise HTTPException(status_code=400, detail="Missing passkey credential data.")

    pk = saas_db.create_passkey(
        user_id=user["id"],
        credential_id=cred_id,
        public_key=raw_id,
        name=key_name
    )
    return {"status": "ok", "passkey": pk}


@router.post("/passkey/delete")
async def passkey_delete(payload: Dict[str, Any], user: Dict[str, Any] = Depends(require_auth)):
    pk_id = payload.get("passkey_id")
    if not pk_id:
        raise HTTPException(status_code=400, detail="passkey_id is required.")
    saas_db.delete_passkey(pk_id, user_id=user["id"])
    return {"status": "ok", "message": "Passkey deleted."}


@router.post("/update_credentials")
async def update_credentials(req: UpdateCredentialsRequest, user: Dict[str, Any] = Depends(require_auth)):
    if req.new_password:
        if not req.current_password or not saas_auth.verify_password(req.current_password, user.get("password_hash"), user.get("salt")):
            raise HTTPException(status_code=400, detail="Current password incorrect.")
        p_hash, salt = saas_auth.hash_password(req.new_password)
        saas_db.update_user_credentials(user["id"], password_hash=p_hash, salt=salt)

    if req.email or req.full_name:
        if req.email and req.email.lower() != user["email"].lower():
            existing = saas_db.get_user_by_email(req.email)
            if existing and existing["id"] != user["id"]:
                raise HTTPException(status_code=400, detail="Email already in use.")
        saas_db.update_user_credentials(user["id"], email=req.email, full_name=req.full_name)

    updated = saas_db.get_user_by_id(user["id"])
    company = saas_db.get_company_by_id(updated["company_id"])
    updated["company"] = company
    return {"status": "ok", "user": _format_user_payload(updated)}
