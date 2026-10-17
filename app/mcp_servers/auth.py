
import os
import time
from functools import lru_cache

import jwt
import requests
from jwt import PyJWKClient


PORTAL_URL = os.getenv(
    "PORTAL_URL", "http://app:8000"
).rstrip("/")

ISSUER = os.getenv(
    "PUBLIC_BASE_URL", "http://localhost:8000"
).rstrip("/")

CITIZEN_AUDIENCE = os.getenv(
    "CITIZEN_MCP_AUDIENCE", "http://localhost:8101"
)

OFFICER_AUDIENCE = os.getenv(
    "OFFICER_MCP_AUDIENCE", "http://localhost:8102"
)


@lru_cache(maxsize=1)
def get_jwks_client():
    return PyJWKClient(
        f"{PORTAL_URL}/.well-known/jwks.json",
        cache_keys=True,
        lifespan=300,
    )


def authenticate_token(token: str, audience: str, role: str) -> dict:
    """Validate a portal-issued JWT for one MCP server."""
    try:
        signing_key = get_jwks_client().get_signing_key_from_jwt(token)

        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=audience,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "iss", "sub", "aud"]},
        )
    except (jwt.PyJWTError, requests.RequestException, ValueError) as exc:
        raise PermissionError("Invalid or expired access token") from exc

    if claims.get("role") != role:
        raise PermissionError("This account cannot access this MCP server")

    if claims.get("scope") != role:
        raise PermissionError("Required OAuth scope is missing")

    subject = claims.get("sub", "")
    expected_prefix = "citizen:" if role == "citizen" else "officer:"

    if not isinstance(subject, str) or not subject.startswith(expected_prefix):
        raise PermissionError("Invalid token subject")

    if claims.get("kind", "access") not in ("access", "program"):
        raise PermissionError("This token type is not permitted")

    if claims.get("kind") == "program" and role != "officer":
        raise PermissionError("Program tokens are only valid for officers")

    return claims


def bearer_token(headers) -> str:
    """Extract a Bearer token from ASGI headers."""
    authorization = dict(headers).get(b"authorization", b"").decode(
        "latin-1"
    )
    scheme, separator, token = authorization.partition(" ")

    if not separator or scheme.lower() != "bearer" or not token.strip():
        raise PermissionError("A Bearer access token is required")

    return token.strip()
