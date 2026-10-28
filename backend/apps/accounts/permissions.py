"""
RBAC & Permission Management for VeloRoster Pro
Production-grade Role-Based Access Control and Tenant Boundary Enforcement.
"""
from functools import wraps
from django.http import JsonResponse
from django.utils import timezone


# -----------------------------------------------------------------------------
# Permission Constants
# -----------------------------------------------------------------------------
PERM_PLATFORM_MANAGE = 'platform:manage'          # Access SuperAdmin Hub, global metrics, keep-alive
PERM_PLANS_MANAGE = 'plans:manage'                # Create, update, delete subscription plans
PERM_COMPANIES_MANAGE = 'companies:manage'        # Create, edit, delete, suspend organizations
PERM_COMPANIES_VIEW_ANY = 'companies:view_any'    # Inspect any tenant
PERM_USERS_MANAGE_ANY = 'users:manage_any'        # Assign users across tenants, alter any role

PERM_TEAM_VIEW = 'team:view'                      # View company members and pending invitations
PERM_TEAM_INVITE = 'team:invite'                  # Invite new staff members to own organization
PERM_TEAM_MANAGE_ROLES = 'team:manage_roles'      # Promote/demote members within own organization
PERM_TEAM_REMOVE = 'team:remove'                  # Remove staff from own organization
PERM_TEAM_REVOKE_INVITE = 'team:revoke_invite'    # Revoke pending invitation

PERM_STUDIO_ACCESS = 'studio:access'              # Access photo studio and rosters
PERM_STUDIO_EDIT = 'studio:edit'                  # Edit player photos, guidelines, auto-frame
PERM_STUDIO_EXPORT = 'studio:export'              # Export batch packages & roster archives


# -----------------------------------------------------------------------------
# Role Permissions Matrix
# -----------------------------------------------------------------------------
ROLE_PERMISSIONS = {
    'superadmin': {
        PERM_PLATFORM_MANAGE,
        PERM_PLANS_MANAGE,
        PERM_COMPANIES_MANAGE,
        PERM_COMPANIES_VIEW_ANY,
        PERM_USERS_MANAGE_ANY,
        PERM_TEAM_VIEW,
        PERM_TEAM_INVITE,
        PERM_TEAM_MANAGE_ROLES,
        PERM_TEAM_REMOVE,
        PERM_TEAM_REVOKE_INVITE,
        PERM_STUDIO_ACCESS,
        PERM_STUDIO_EDIT,
        PERM_STUDIO_EXPORT,
    },
    'company_admin': {
        PERM_TEAM_VIEW,
        PERM_TEAM_INVITE,
        PERM_TEAM_MANAGE_ROLES,
        PERM_TEAM_REMOVE,
        PERM_TEAM_REVOKE_INVITE,
        PERM_STUDIO_ACCESS,
        PERM_STUDIO_EDIT,
        PERM_STUDIO_EXPORT,
    },
    'member': {
        PERM_STUDIO_ACCESS,
        PERM_STUDIO_EDIT,
        PERM_STUDIO_EXPORT,
    },
    'viewer': {
        PERM_STUDIO_ACCESS,
    },
}


def get_user_permissions(user):
    """Returns set of permission strings for the user."""
    if not user or not user.is_authenticated:
        return set()
    if user.is_superuser or user.role == 'superadmin':
        return set(ROLE_PERMISSIONS['superadmin'])
    return set(ROLE_PERMISSIONS.get(user.role, set()))


def has_permission(user, perm):
    """Checks if a user has a specific permission."""
    return perm in get_user_permissions(user)


def error_json(message, code='FORBIDDEN', status=403, details=None):
    payload = {
        "status": "error",
        "code": code,
        "message": message,
    }
    if details:
        payload["details"] = details
    return JsonResponse(payload, status=status)


# -----------------------------------------------------------------------------
# Decorators
# -----------------------------------------------------------------------------
def require_auth(view_func):
    """Requires an authenticated user session."""
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return error_json("Authentication required. Please log in.", code="UNAUTHENTICATED", status=401)
        return view_func(request, *args, **kwargs)
    return _wrapped


def require_role(*allowed_roles):
    """Requires the user to have one of the specified roles."""
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return error_json("Authentication required. Please log in.", code="UNAUTHENTICATED", status=401)

            # Superadmin / is_superuser bypass
            if request.user.is_superuser or request.user.role == 'superadmin':
                return view_func(request, *args, **kwargs)

            if request.user.role not in allowed_roles:
                return error_json(
                    f"Access denied: role '{request.user.role}' lacks permission for this action. "
                    f"Required: {', '.join(allowed_roles)}.",
                    code="FORBIDDEN_ROLE",
                    status=403
                )
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator


def require_perm(perm_name):
    """Requires the user to have the specific granular permission."""
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return error_json("Authentication required. Please log in.", code="UNAUTHENTICATED", status=401)

            if not has_permission(request.user, perm_name):
                return error_json(
                    f"Permission denied: action requires '{perm_name}'.",
                    code="FORBIDDEN_PERMISSION",
                    status=403
                )
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator
