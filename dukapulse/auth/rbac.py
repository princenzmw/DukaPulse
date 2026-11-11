"""Role-Based Access Control (RBAC) dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .jwt import Auth0Validator, TokenPayload

security = HTTPBearer(auto_error=False)
validator = Auth0Validator()


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(security)],
) -> TokenPayload:
    """Extract and verify bearer token from Authorization header."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return validator.verify_token(credentials.credentials)
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(err),
            headers={"WWW-Authenticate": "Bearer"},
        ) from err


def require_role(required_role: str):
    """Enforce minimum role requirement (owner > staff)."""

    async def role_checker(
        user: Annotated[TokenPayload, Depends(get_current_user)],
    ) -> TokenPayload:
        if required_role == "owner" and user.role != "owner":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: this action requires 'owner' privileges. Current role: '{user.role}'",
            )
        return user

    return role_checker


RequireOwner = Annotated[TokenPayload, Depends(require_role("owner"))]
RequireStaff = Annotated[TokenPayload, Depends(require_role("staff"))]
