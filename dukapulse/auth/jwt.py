"""Auth0 JWT validation and security flows."""

from __future__ import annotations

import logging
import time
from typing import Any

import jwt
from jwt import PyJWKClient
from pydantic import BaseModel, Field

from ..config import settings

logger = logging.getLogger(__name__)


class TokenPayload(BaseModel):
    """Normalized representation of verified Auth0 token."""

    sub: str = Field(description="Auth0 user ID")
    email: str | None = None
    role: str = Field(default="staff", description="Assigned role: 'owner' or 'staff'")
    shop_id: str | None = Field(default=None, description="Tenant shop ID")
    permissions: list[str] = Field(default_factory=list)
    exp: int


class Auth0Validator:
    """Verifies incoming Bearer tokens using Auth0 JWKS or mock dev keys."""

    def __init__(self) -> None:
        self.domain = settings.AUTH0_DOMAIN
        self.audience = settings.AUTH0_API_AUDIENCE
        self.jwks_url = f"https://{self.domain}/.well-known/jwks.json"
        self._jwks_client: PyJWKClient | None = None

    @property
    def jwks_client(self) -> PyJWKClient:
        if self._jwks_client is None:
            self._jwks_client = PyJWKClient(self.jwks_url)
        return self._jwks_client

    def verify_token(self, token: str) -> TokenPayload:
        """Decode and verify JWT against Auth0 or local dev signature."""
        # Check unverified header to determine algorithm
        unverified_header = jwt.get_unverified_header(token)
        alg = unverified_header.get("alg", "RS256")

        if alg == "HS256" and settings.DEV_MODE_MOCK_AUTH:
            # Verified with local developer secret
            payload = jwt.decode(
                token,
                settings.DEV_JWT_SECRET,
                algorithms=["HS256"],
                audience=self.audience,
            )
            return self._build_token_payload(payload)

        # Production Auth0 RS256 flow
        try:
            signing_key = self.jwks_client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=f"https://{self.domain}/",
            )
            return self._build_token_payload(payload)
        except Exception as exc:
            logger.error("Auth0 token verification failed: %s", exc)
            raise ValueError(f"Invalid or expired Auth0 JWT: {exc}") from exc

    def _build_token_payload(self, claims: dict[str, Any]) -> TokenPayload:
        # Extract custom claims or Auth0 RBAC roles
        roles = claims.get("https://dukapulse.africa/roles", claims.get("roles", []))
        if isinstance(roles, str):
            roles = [roles]

        primary_role = "owner" if "owner" in roles or "duka_owner" in roles else "staff"
        shop_id = claims.get("https://dukapulse.africa/shop_id", claims.get("shop_id"))

        return TokenPayload(
            sub=claims.get("sub", "anonymous"),
            email=claims.get("email"),
            role=primary_role,
            shop_id=shop_id,
            permissions=claims.get("permissions", []),
            exp=claims.get("exp", int(time.time()) + 3600),
        )


def create_dev_token(
    sub: str,
    role: str = "staff",
    shop_id: str | None = None,
    expires_in: int = 86400,
) -> str:
    """Generate a test JWT token for offline hackathon judging and CI tests."""
    now = int(time.time())
    payload = {
        "sub": sub,
        "email": f"{sub}@dukapulse.internal",
        "roles": [f"duka_{role}", role],
        "https://dukapulse.africa/roles": [f"duka_{role}", role],
        "https://dukapulse.africa/shop_id": shop_id,
        "shop_id": shop_id,
        "aud": settings.AUTH0_API_AUDIENCE,
        "iss": f"https://{settings.AUTH0_DOMAIN}/",
        "iat": now,
        "exp": now + expires_in,
    }
    return jwt.encode(payload, settings.DEV_JWT_SECRET, algorithm="HS256")
