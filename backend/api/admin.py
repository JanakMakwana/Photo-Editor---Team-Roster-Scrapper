"""
Admin & Organization Management API endpoints.
Enforces strict Role-Based Access Control (RBAC).
"""

from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Request, HTTPException, status, Depends
from pydantic import BaseModel
import saas_db
import saas_auth
import saas_email
from backend.core.rbac import require_auth, require_superadmin, require_company_admin

router = APIRouter(prefix="/api", tags=["Admin & Organization"])


class CreateCompanyRequest(BaseModel):
    name: str
    plan: Optional[str] = "team"
    max_seats: Optional[int] = 10
    admin_email: Optional[str] = None
    admin_name: Optional[str] = None


class UpdateCompanyPlanRequest(BaseModel):
    company_id: str
    plan: str
    max_seats: int
    status: Optional[str] = "active"


class InviteMemberRequest(BaseModel):
    email: str
    name: Optional[str] = None
    role: Optional[str] = "member"
    company_id: Optional[str] = None


class BulkInviteRequest(BaseModel):
    raw_text: str
    company_id: Optional[str] = None


class UserStatusRequest(BaseModel):
    user_id: str
    is_active: bool


class DeleteUserRequest(BaseModel):
    user_id: str


# --------------------------------------------------------------------------
# Platform SuperAdmin Fleet Dashboard
# --------------------------------------------------------------------------

@router.get("/admin/dashboard_stats")
@router.get("/admin/metrics")
async def get_dashboard_stats(_: Dict[str, Any] = Depends(require_superadmin)):
    metrics = saas_db.get_platform_metrics()
    return {"status": "ok", "metrics": metrics, **(metrics or {})}


@router.get("/admin/companies")
async def list_companies(_: Dict[str, Any] = Depends(require_superadmin)):
    companies = saas_db.get_all_companies()
    return {"status": "ok", "companies": companies}


@router.post("/admin/companies/create")
async def create_company(req: CreateCompanyRequest, request: Request, _: Dict[str, Any] = Depends(require_superadmin)):
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Company name is required.")

    comp = saas_db.create_company(name=name, plan=req.plan, max_seats=req.max_seats)

    admin_user = None
    activation_url = None
    if req.admin_email and "@" in req.admin_email:
        email = req.admin_email.strip().lower()
        if not saas_db.get_user_by_email(email):
            inv_tok = saas_auth.generate_invite_token()
            admin_user = saas_db.create_user(
                company_id=comp["id"],
                email=email,
                full_name=req.admin_name or "Company Administrator",
                role="company_admin",
                invite_token=inv_tok
            )
            base_url = str(request.base_url).rstrip("/")
            saas_email.send_invitation_email(email, req.admin_name or "Admin", comp["name"], inv_tok, base_url)
            activation_url = f"{base_url}/#activate?token={inv_tok}"

    return {
        "status": "ok",
        "company": comp,
        "admin_user": admin_user,
        "activation_url": activation_url
    }


@router.post("/admin/companies/update_plan")
async def update_company_plan(req: UpdateCompanyPlanRequest, _: Dict[str, Any] = Depends(require_superadmin)):
    updated = saas_db.update_company_plan(
        company_id=req.company_id,
        plan=req.plan,
        max_seats=req.max_seats,
        status=req.status
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Company not found.")
    return {"status": "ok", "company": updated}


# --------------------------------------------------------------------------
# Organization Team Management & Seat Allocations
# --------------------------------------------------------------------------

@router.get("/company/details")
async def get_company_details(user: Dict[str, Any] = Depends(require_auth)):
    company_id = user.get("company_id")
    if not company_id:
        if user.get("role") == "superadmin":
            # Superadmin viewing first company by default
            comps = saas_db.get_all_companies()
            if comps:
                company_id = comps[0]["id"]
            else:
                return {"status": "ok", "company": None}
        else:
            raise HTTPException(status_code=400, detail="No organization associated with this account.")

    company = saas_db.get_company_by_id(company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")

    used = saas_db.get_company_seat_count(company["id"])
    company["used_seats"] = used
    company["remaining_seats"] = max(0, company.get("max_seats", 10) - used)
    return {"status": "ok", "company": company}


@router.get("/company/users")
async def list_company_users(
    company_id: Optional[str] = None,
    request: Request = None,
    user: Dict[str, Any] = Depends(require_auth)
):
    target_company_id = company_id if (user["role"] == "superadmin" and company_id) else user.get("company_id")
    if not target_company_id:
        raise HTTPException(status_code=400, detail="Target company ID is required.")

    company = saas_db.get_company_by_id(target_company_id)
    members = saas_db.get_users_by_company(target_company_id)
    base_url = str(request.base_url).rstrip("/") if request else "http://localhost:8000"
    is_admin = user["role"] in ("superadmin", "company_admin")

    cleaned_members = []
    for m in members:
        m_dict = dict(m)
        m_dict.pop("password_hash", None)
        m_dict.pop("salt", None)
        if is_admin and m_dict.get("invite_token"):
            m_dict["activation_url"] = f"{base_url}/#activate?token={m_dict['invite_token']}"
        else:
            m_dict["activation_url"] = None
            if not is_admin:
                m_dict.pop("invite_token", None)
        cleaned_members.append(m_dict)

    used = saas_db.get_company_seat_count(target_company_id)
    max_seats = company.get("max_seats", 10) if company else 10

    return {
        "status": "ok",
        "company": company,
        "used_seats": used,
        "max_seats": max_seats,
        "remaining_seats": max(0, max_seats - used),
        "users": cleaned_members
    }


@router.post("/company/users/invite")
async def invite_member(req: InviteMemberRequest, request: Request, user: Dict[str, Any] = Depends(require_company_admin)):
    target_cid = req.company_id if (user["role"] == "superadmin" and req.company_id) else user.get("company_id")
    company = saas_db.get_company_by_id(target_cid)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")

    # Seat quota verification
    used = saas_db.get_company_seat_count(target_cid)
    max_seats = company.get("max_seats", 10)
    if used >= max_seats:
        raise HTTPException(status_code=403, detail=f"Seat limit reached ({used}/{max_seats}). Upgrade plan to invite more team members.")

    email = req.email.strip().lower()
    if saas_db.get_user_by_email(email):
        raise HTTPException(status_code=400, detail="A user with this email address already exists.")

    inv_tok = saas_auth.generate_invite_token()
    name = req.name or email.split("@")[0].title()
    role = req.role if req.role in ("member", "company_admin") else "member"

    # Only superadmin can designate another company admin
    if role == "company_admin" and user["role"] != "superadmin":
        role = "member"

    new_user = saas_db.create_user(target_cid, email, name, role=role, invite_token=inv_tok)
    base_url = str(request.base_url).rstrip("/")
    saas_email.send_invitation_email(email, name, company["name"], inv_tok, base_url)

    return {
        "status": "ok",
        "user": new_user,
        "activation_url": f"{base_url}/#activate?token={inv_tok}",
        "used_seats": saas_db.get_company_seat_count(target_cid),
        "max_seats": max_seats
    }


@router.post("/company/users/bulk_invite")
async def bulk_invite_members(req: BulkInviteRequest, request: Request, user: Dict[str, Any] = Depends(require_company_admin)):
    target_cid = req.company_id if (user["role"] == "superadmin" and req.company_id) else user.get("company_id")
    company = saas_db.get_company_by_id(target_cid)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")

    parsed_users = saas_auth.parse_bulk_user_input(req.raw_text)
    if not parsed_users:
        raise HTTPException(status_code=400, detail="No valid email addresses found in pasted text.")

    used = saas_db.get_company_seat_count(target_cid)
    max_seats = company.get("max_seats", 10)
    avail = max(0, max_seats - used)

    if len(parsed_users) > avail:
        raise HTTPException(status_code=403, detail=f"Cannot invite {len(parsed_users)} users. Only {avail} seats available ({used}/{max_seats}).")

    base_url = str(request.base_url).rstrip("/")
    invited = []
    skipped = []

    for u in parsed_users:
        email = u["email"]
        if saas_db.get_user_by_email(email):
            skipped.append(email)
            continue
        inv_tok = saas_auth.generate_invite_token()
        role = u.get("role", "member")
        if role == "company_admin" and user["role"] != "superadmin":
            role = "member"
        created = saas_db.create_user(target_cid, email, u["full_name"], role=role, invite_token=inv_tok)
        saas_email.send_invitation_email(email, u["full_name"], company["name"], inv_tok, base_url)
        invited.append({"email": email, "name": u["full_name"], "role": role})

    return {
        "status": "ok",
        "invited_count": len(invited),
        "skipped_count": len(skipped),
        "invited": invited,
        "skipped": skipped,
        "used_seats": saas_db.get_company_seat_count(target_cid),
        "max_seats": max_seats
    }


@router.post("/company/users/status")
async def toggle_user_status(req: UserStatusRequest, user: Dict[str, Any] = Depends(require_company_admin)):
    target_user = saas_db.get_user_by_id(req.user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found.")

    if user["role"] != "superadmin" and target_user["company_id"] != user["company_id"]:
        raise HTTPException(status_code=403, detail="Forbidden: User belongs to another organization.")

    if target_user["role"] == "superadmin":
        raise HTTPException(status_code=403, detail="Cannot alter status of SuperAdmin user.")

    saas_db.update_user_status(req.user_id, req.is_active)
    return {"status": "ok", "is_active": req.is_active}


@router.post("/company/users/delete")
async def delete_member(req: DeleteUserRequest, user: Dict[str, Any] = Depends(require_company_admin)):
    target_user = saas_db.get_user_by_id(req.user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found.")

    if user["role"] != "superadmin" and target_user["company_id"] != user["company_id"]:
        raise HTTPException(status_code=403, detail="Forbidden: User belongs to another organization.")

    if target_user["role"] == "superadmin":
        raise HTTPException(status_code=403, detail="Cannot delete SuperAdmin.")

    if target_user["id"] == user["id"]:
        raise HTTPException(status_code=400, detail="Cannot delete your own active account.")

    saas_db.delete_user(req.user_id)
    return {"status": "ok", "message": "User deleted successfully."}
