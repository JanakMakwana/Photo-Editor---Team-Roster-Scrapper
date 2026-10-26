"""
Role-Based Access Control (RBAC) & Security Dependencies for FastAPI.
Roles:
  - 'superadmin': Global platform administrator across all organizations (unmetered, root scope).
  - 'company_admin': Organization administrator (manages organization seats & invitations).
  - 'member': Regular athletic media editor (accesses studio workbench & scraper).
"""

from typing import Optional, Dict, Any, List
from fastapi import Request, HTTPException, status, Depends
import saas_auth
import saas_db


async def get_current_user(request: Request) -> Optional[Dict[str, Any]]:
    """
    Extracts the authenticated user from the Authorization header (Bearer) or Cookie (session_token).
    Returns None if unauthenticated.
    """
    try:
        user = saas_auth.get_authenticated_user(request.headers)
        return user
    except Exception as e:
        print(f"[RBAC Error] Failed to extract user: {e}")
        return None


async def require_auth(user: Optional[Dict[str, Any]] = Depends(get_current_user)) -> Dict[str, Any]:
    """Dependency that ensures the user is logged in with an active account."""
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please sign in to access VeloRoster AI services.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.get("is_active"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive or deactivated. Please contact your organization administrator.",
        )
    return user


def require_role(allowed_roles: List[str]):
    """Factory dependency that restricts access to specific roles."""
    async def role_checker(user: Dict[str, Any] = Depends(require_auth)) -> Dict[str, Any]:
        user_role = user.get("role", "member")
        if user_role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: Action requires one of roles: {', '.join(allowed_roles)} (current role: {user_role}).",
            )
        return user
    return role_checker


# Convenient pre-configured role dependencies
require_superadmin = require_role(["superadmin"])
require_company_admin = require_role(["superadmin", "company_admin"])
