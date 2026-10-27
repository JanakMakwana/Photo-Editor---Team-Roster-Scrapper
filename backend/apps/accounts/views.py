import json
import secrets
from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from .models import User, Company, Invitation


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
