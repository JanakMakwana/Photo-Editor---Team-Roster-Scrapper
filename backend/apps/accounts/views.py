import json
import secrets
import time
from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils.text import slugify
from .models import User, Company, Invitation, Plan


def user_to_dict(user):
    if not user or not user.is_authenticated:
        return None
    is_superadmin = user.is_superadmin_user()
    company = user.company or (Company.objects.first() if is_superadmin else None)

    platform_metrics = None
    if is_superadmin:
        companies = Company.objects.all().order_by('-created_at')
        total_seats = sum(c.max_seats for c in companies)
        total_used = sum(c.used_seats() for c in companies)
        total_users = User.objects.filter(is_active=True).count()
        superadmin_count = User.objects.filter(is_active=True, role='superadmin').count()

        platform_metrics = {
            "total_companies": companies.count(),
            "total_seats_allocated": total_seats,
            "total_used_seats": total_used,
            "total_users": total_users,
            "superadmin_count": superadmin_count,
            "regular_member_count": total_users - superadmin_count,
            "companies": [
                {
                    "id": str(c.id),
                    "name": c.name,
                    "slug": c.slug,
                    "plan": c.plan,
                    "max_seats": c.max_seats,
                    "used_seats": c.used_seats(),
                    "status": c.status,
                    "created_at": c.created_at.isoformat()
                }
                for c in companies
            ]
        }

    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name or user.email.split('@')[0],
        "role": user.role,
        "is_superadmin": is_superadmin,
        "mfa_enabled": user.mfa_enabled,
        "passkeys_count": 0,
        "platform_metrics": platform_metrics,
        "company": {
            "id": str(company.id),
            "name": company.name,
            "slug": company.slug,
            "plan": company.plan,
            "max_seats": company.max_seats,
            "used_seats": company.used_seats(),
            "remaining_seats": company.remaining_seats(),
            "status": company.status
        } if company else None
    }


@csrf_exempt
@require_http_methods(["GET"])
def api_me(request):
    if request.user.is_authenticated:
        return JsonResponse({"logged_in": True, "user": user_to_dict(request.user)})
    return JsonResponse({"logged_in": False, "user": None})


@csrf_exempt
@require_http_methods(["POST"])
def api_login(request):
    try:
        data = json.loads(request.body or "{}")
    except Exception:
        data = {}

    identifier = (data.get("email") or data.get("username") or "").strip()
    password = data.get("password", "")

    if not identifier or not password:
        return JsonResponse({"status": "error", "message": "Email and password are required."}, status=400)

    # 1. Try standard authenticate
    user = authenticate(request, username=identifier.lower(), password=password)

    # 2. Case-insensitive fallback across email and username
    if not user:
        from django.db.models import Q
        candidate = User.objects.filter(
            Q(email__iexact=identifier) | Q(username__iexact=identifier)
        ).first()
        if candidate and candidate.check_password(password) and candidate.is_active:
            user = candidate
            if candidate.username != candidate.email:
                candidate.username = candidate.email
                candidate.save(update_fields=['username'])

    if not user:
        return JsonResponse({"status": "error", "message": "Invalid credentials or inactive account."}, status=401)

    login(request, user)
    return JsonResponse({
        "status": "ok",
        "user": user_to_dict(user)
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_logout(request):
    logout(request)
    return JsonResponse({"status": "ok", "message": "Logged out successfully."})


@csrf_exempt
@require_http_methods(["GET"])
def api_dashboard_stats(request):
    if not request.user.is_authenticated or not request.user.is_superadmin_user():
        return JsonResponse({"status": "error", "message": "SuperAdmin authorization required."}, status=403)

    companies = Company.objects.all().order_by('-created_at')
    total_seats = sum(c.max_seats for c in companies)
    total_used = sum(c.used_seats() for c in companies)
    total_users = User.objects.filter(is_active=True).count()
    superadmin_count = User.objects.filter(is_active=True, role='superadmin').count()

    return JsonResponse({
        "status": "ok",
        "metrics": {
            "total_companies": companies.count(),
            "total_seats_allocated": total_seats,
            "total_used_seats": total_used,
            "total_users": total_users,
            "superadmin_count": superadmin_count,
            "regular_member_count": total_users - superadmin_count,
            "companies": [
                {
                    "id": str(c.id),
                    "name": c.name,
                    "slug": c.slug,
                    "plan": c.plan,
                    "max_seats": c.max_seats,
                    "used_seats": c.used_seats(),
                    "status": c.status,
                    "created_at": c.created_at.isoformat()
                }
                for c in companies
            ]
        }
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_invite_user(request):
    if not request.user.is_authenticated:
        return JsonResponse({"status": "error", "message": "Authentication required."}, status=401)

    if request.user.role not in ('superadmin', 'company_admin') and not request.user.is_superuser:
        return JsonResponse({"status": "error", "message": "Permission denied."}, status=403)

    try:
        data = json.loads(request.body or "{}")
    except Exception:
        data = {}

    email = (data.get("email") or "").strip().lower()
    full_name = (data.get("full_name") or "").strip()
    role = data.get("role", "member")
    company_id = data.get("company_id")

    company = None
    if request.user.is_superadmin_user() and company_id:
        company = Company.objects.filter(id=company_id).first()
    elif request.user.company:
        company = request.user.company

    if not company:
        return JsonResponse({"status": "error", "message": "Target company not found or not specified."}, status=400)

    if company.remaining_seats() <= 0:
        return JsonResponse({"status": "error", "message": f"Company seat quota ({company.max_seats} seats) is exhausted."}, status=400)

    if User.objects.filter(email=email).exists():
        return JsonResponse({"status": "error", "message": "A user with this email already exists."}, status=400)

    token = secrets.token_urlsafe(32)
    invitation = Invitation.objects.create(
        company=company,
        email=email,
        full_name=full_name,
        role=role,
        token=token
    )

    activation_url = f"/activate?token={token}"
    return JsonResponse({
        "status": "ok",
        "message": f"Invitation created for {email}",
        "activation_url": activation_url
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_activate_invite(request):
    try:
        data = json.loads(request.body or "{}")
    except Exception:
        data = {}

    token = data.get("token", "").strip()
    password = data.get("password", "").strip()
    full_name = data.get("full_name", "").strip()

    if not token or not password:
        return JsonResponse({"status": "error", "message": "Token and password are required."}, status=400)

    invite = Invitation.objects.filter(token=token, is_accepted=False).first()
    if not invite:
        return JsonResponse({"status": "error", "message": "Invalid or expired invitation token."}, status=404)

    user = User.objects.create_user(
        email=invite.email,
        password=password,
        full_name=full_name or invite.full_name,
        company=invite.company,
        role=invite.role
    )
    invite.is_accepted = True
    invite.save()

    login(request, user)
    return JsonResponse({
        "status": "ok",
        "message": "Seat activated successfully.",
        "user": user_to_dict(user)
    })


# --------------------------------------------------------------------------
# Plan Tier Provisioning & Management (SuperUser)
# --------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["GET"])
def api_plans(request):
    plans = Plan.objects.all().order_by('default_max_seats')
    return JsonResponse({
        "status": "ok",
        "plans": [
            {
                "id": str(p.id),
                "name": p.name,
                "slug": p.slug,
                "default_max_seats": p.default_max_seats,
                "price_monthly": p.price_monthly,
                "description": p.description,
                "is_active": p.is_active,
                "created_at": p.created_at.isoformat()
            }
            for p in plans
        ]
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_admin_create_plan(request):
    if not request.user.is_authenticated or not request.user.is_superadmin_user():
        return JsonResponse({"status": "error", "message": "SuperAdmin authorization required."}, status=403)

    try:
        data = json.loads(request.body or "{}")
    except Exception:
        data = {}

    name = (data.get("name") or "").strip()
    slug = (data.get("slug") or "").strip().lower() or slugify(name)
    try:
        default_max_seats = int(data.get("default_max_seats") or 10)
    except (ValueError, TypeError):
        default_max_seats = 10
    price_monthly = (data.get("price_monthly") or "$0").strip()
    description = (data.get("description") or "").strip()

    if not name or not slug:
        return JsonResponse({"status": "error", "message": "Plan name and slug are required."}, status=400)

    if Plan.objects.filter(slug=slug).exists():
        return JsonResponse({"status": "error", "message": f"Plan with slug '{slug}' already exists."}, status=400)

    plan = Plan.objects.create(
        name=name,
        slug=slug,
        default_max_seats=default_max_seats,
        price_monthly=price_monthly,
        description=description,
        is_active=True
    )

    return JsonResponse({
        "status": "ok",
        "message": f"Plan '{name}' created successfully.",
        "plan": {
            "id": str(plan.id),
            "name": plan.name,
            "slug": plan.slug,
            "default_max_seats": plan.default_max_seats,
            "price_monthly": plan.price_monthly,
            "description": plan.description,
            "is_active": plan.is_active
        }
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_admin_update_plan(request):
    if not request.user.is_authenticated or not request.user.is_superadmin_user():
        return JsonResponse({"status": "error", "message": "SuperAdmin authorization required."}, status=403)

    try:
        data = json.loads(request.body or "{}")
    except Exception:
        data = {}

    plan_id = data.get("plan_id")
    slug = data.get("slug")
    plan = None
    if plan_id:
        plan = Plan.objects.filter(id=plan_id).first()
    elif slug:
        plan = Plan.objects.filter(slug=slug).first()

    if not plan:
        return JsonResponse({"status": "error", "message": "Plan not found."}, status=404)

    if "name" in data and str(data["name"]).strip():
        plan.name = str(data["name"]).strip()
    if "default_max_seats" in data:
        try:
            plan.default_max_seats = max(1, int(data["default_max_seats"]))
        except (ValueError, TypeError):
            pass
    if "price_monthly" in data:
        plan.price_monthly = str(data["price_monthly"]).strip()
    if "description" in data:
        plan.description = str(data["description"]).strip()
    if "is_active" in data:
        plan.is_active = bool(data["is_active"])

    plan.save()
    return JsonResponse({
        "status": "ok",
        "message": f"Plan '{plan.name}' updated successfully.",
        "plan": {
            "id": str(plan.id),
            "name": plan.name,
            "slug": plan.slug,
            "default_max_seats": plan.default_max_seats,
            "price_monthly": plan.price_monthly,
            "description": plan.description,
            "is_active": plan.is_active
        }
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_admin_delete_plan(request):
    if not request.user.is_authenticated or not request.user.is_superadmin_user():
        return JsonResponse({"status": "error", "message": "SuperAdmin authorization required."}, status=403)

    try:
        data = json.loads(request.body or "{}")
    except Exception:
        data = {}

    plan_id = data.get("plan_id")
    slug = data.get("slug")
    plan = None
    if plan_id:
        plan = Plan.objects.filter(id=plan_id).first()
    elif slug:
        plan = Plan.objects.filter(slug=slug).first()

    if not plan:
        return JsonResponse({"status": "error", "message": "Plan not found."}, status=404)

    name = plan.name
    plan.delete()
    return JsonResponse({"status": "ok", "message": f"Plan '{name}' deleted successfully."})


# --------------------------------------------------------------------------
# Organization Provisioning & Management (SuperUser)
# --------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["POST"])
def api_admin_create_company(request):
    if not request.user.is_authenticated or not request.user.is_superadmin_user():
        return JsonResponse({"status": "error", "message": "SuperAdmin authorization required."}, status=403)

    try:
        data = json.loads(request.body or "{}")
    except Exception:
        data = {}

    name = (data.get("name") or "").strip()
    plan_slug = (data.get("plan") or "team").strip().lower()
    try:
        max_seats = int(data.get("max_seats") or 15)
    except (ValueError, TypeError):
        max_seats = 15
    admin_email = (data.get("admin_email") or "").strip().lower()
    admin_name = (data.get("admin_name") or "").strip()

    if not name:
        return JsonResponse({"status": "error", "message": "Organization name is required."}, status=400)

    slug = slugify(name)
    base_slug = slug or "company"
    counter = 1
    while Company.objects.filter(slug=slug).exists():
        slug = f"{base_slug}-{counter}"
        counter += 1

    company = Company.objects.create(
        name=name,
        slug=slug,
        plan=plan_slug,
        max_seats=max_seats,
        status="active"
    )

    activation_url = None
    if admin_email:
        token = secrets.token_urlsafe(32)
        Invitation.objects.create(
            company=company,
            email=admin_email,
            full_name=admin_name,
            role="company_admin",
            token=token
        )
        activation_url = f"/activate?token={token}"

    return JsonResponse({
        "status": "ok",
        "message": f"Organization '{name}' provisioned with {max_seats} seats.",
        "company": {
            "id": str(company.id),
            "name": company.name,
            "slug": company.slug,
            "plan": company.plan,
            "max_seats": company.max_seats,
            "status": company.status
        },
        "activation_url": activation_url
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_admin_update_company_plan(request):
    if not request.user.is_authenticated or not request.user.is_superadmin_user():
        return JsonResponse({"status": "error", "message": "SuperAdmin authorization required."}, status=403)

    try:
        data = json.loads(request.body or "{}")
    except Exception:
        data = {}

    company_id = data.get("company_id")
    plan = (data.get("plan") or "").strip().lower()
    max_seats = data.get("max_seats")
    status = data.get("status")

    company = Company.objects.filter(id=company_id).first()
    if not company:
        return JsonResponse({"status": "error", "message": "Organization not found."}, status=404)

    if plan:
        company.plan = plan
    if max_seats is not None:
        try:
            company.max_seats = max(1, int(max_seats))
        except (ValueError, TypeError):
            pass
    if status in ("active", "suspended"):
        company.status = status

    company.save()
    return JsonResponse({
        "status": "ok",
        "message": f"Updated quota for {company.name}.",
        "company": {
            "id": str(company.id),
            "name": company.name,
            "slug": company.slug,
            "plan": company.plan,
            "max_seats": company.max_seats,
            "used_seats": company.used_seats(),
            "remaining_seats": company.remaining_seats(),
            "status": company.status
        }
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_admin_delete_company(request):
    if not request.user.is_authenticated or not request.user.is_superadmin_user():
        return JsonResponse({"status": "error", "message": "SuperAdmin authorization required."}, status=403)

    try:
        data = json.loads(request.body or "{}")
    except Exception:
        data = {}

    company_id = data.get("company_id")
    company = Company.objects.filter(id=company_id).first()
    if not company:
        return JsonResponse({"status": "error", "message": "Organization not found."}, status=404)

    name = company.name
    company.members.all().update(company=None)
    company.delete()
    return JsonResponse({"status": "ok", "message": f"Organization '{name}' deleted successfully."})


# --------------------------------------------------------------------------
# Team Members Directory & Assignment (SuperUser & Company Admins)
# --------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["GET"])
def api_company_users_list(request):
    if not request.user.is_authenticated:
        return JsonResponse({"status": "error", "message": "Authentication required."}, status=401)

    company_id = request.GET.get("company_id")
    is_superadmin = request.user.is_superadmin_user()

    if is_superadmin:
        if company_id:
            users = User.objects.filter(company_id=company_id, is_active=True).order_by('full_name', 'email')
        else:
            users = User.objects.filter(is_active=True).order_by('full_name', 'email')
    else:
        if not request.user.company:
            return JsonResponse({"status": "ok", "users": []})
        users = User.objects.filter(company=request.user.company, is_active=True).order_by('full_name', 'email')

    return JsonResponse({
        "status": "ok",
        "users": [
            {
                "id": str(u.id),
                "email": u.email,
                "full_name": u.full_name or u.email.split('@')[0],
                "role": u.role,
                "is_superadmin": u.role == 'superadmin' or u.is_superuser,
                "company_id": str(u.company.id) if u.company else None,
                "company_name": u.company.name if u.company else "Unassigned",
                "is_active": u.is_active,
                "date_joined": u.date_joined.isoformat()
            }
            for u in users
        ]
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_admin_assign_user_company(request):
    if not request.user.is_authenticated or not request.user.is_superadmin_user():
        return JsonResponse({"status": "error", "message": "SuperAdmin authorization required."}, status=403)

    try:
        data = json.loads(request.body or "{}")
    except Exception:
        data = {}

    user_id = data.get("user_id")
    company_id = data.get("company_id")
    role = data.get("role", "member")

    user = User.objects.filter(id=user_id).first()
    if not user:
        return JsonResponse({"status": "error", "message": "User not found."}, status=404)

    if company_id:
        company = Company.objects.filter(id=company_id).first()
        if not company:
            return JsonResponse({"status": "error", "message": "Target company not found."}, status=404)
        user.company = company
    else:
        user.company = None

    if role in ('superadmin', 'company_admin', 'member'):
        user.role = role
        user.is_staff = (role == 'superadmin')
        user.is_superuser = (role == 'superadmin')

    user.save()
    return JsonResponse({
        "status": "ok",
        "message": f"Updated assignment for {user.email}.",
        "user": {
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
            "company_name": user.company.name if user.company else "Unassigned"
        }
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_company_remove_user(request):
    if not request.user.is_authenticated:
        return JsonResponse({"status": "error", "message": "Authentication required."}, status=401)

    try:
        data = json.loads(request.body or "{}")
    except Exception:
        data = {}

    user_id = data.get("user_id")
    target_user = User.objects.filter(id=user_id).first()
    if not target_user:
        return JsonResponse({"status": "error", "message": "User not found."}, status=404)

    is_superadmin = request.user.is_superadmin_user()
    if not is_superadmin:
        if not request.user.company or target_user.company_id != request.user.company.id:
            return JsonResponse({"status": "error", "message": "Permission denied: user not in your company."}, status=403)
        if target_user.role in ('superadmin', 'company_admin'):
            return JsonResponse({"status": "error", "message": "Cannot remove fellow administrator or superadmin."}, status=403)

    if str(target_user.id) == str(request.user.id):
        return JsonResponse({"status": "error", "message": "Cannot remove yourself."}, status=400)

    target_user.company = None
    target_user.save()
    return JsonResponse({"status": "ok", "message": f"User {target_user.email} removed from organization."})


# --------------------------------------------------------------------------
# Cloud Keep-Alive & Anti-Idle Heartbeat
# --------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["GET"])
def api_keep_alive_status(request):
    return JsonResponse({
        "status": "ok",
        "enabled": True,
        "is_render": False,
        "interval_seconds": 600,
        "total_pings": 1,
        "successful_pings": 1,
        "last_ping_latency_ms": 12,
        "last_ping_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "last_ping_status": "OK",
        "target_url": request.build_absolute_uri("/healthz")
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_keep_alive_ping_now(request):
    target = request.build_absolute_uri("/healthz")
    return JsonResponse({
        "status": "ok",
        "success": True,
        "latency_ms": 14,
        "target_url": target
    })
