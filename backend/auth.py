"""Supabase JWT authentication for protected API routes."""

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any

import jwt
from fastapi import Header, HTTPException, status
from jwt import InvalidTokenError, PyJWKClient, PyJWKClientError

SUPPORTED_ASYMMETRIC_ALGORITHMS = {"RS256", "ES256"}
SUPPORTED_HMAC_ALGORITHMS = {"HS256"}


@dataclass(frozen=True)
class CurrentUser:
    """Authenticated Supabase user derived from verified JWT claims."""

    owner_id: str
    email: str | None
    role: str
    claims: dict[str, Any]


class AuthConfigError(RuntimeError):
    """Raised when the server cannot verify protected requests safely."""


@lru_cache(maxsize=8)
def _jwks_client(jwks_url: str) -> PyJWKClient:
    return PyJWKClient(jwks_url)


def _supabase_url() -> str:
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    if not url:
        raise AuthConfigError("SUPABASE_URL is required for authenticated endpoints")
    if not url.startswith(("https://", "http://localhost", "http://127.0.0.1")):
        raise AuthConfigError("SUPABASE_URL must be an HTTPS URL or a local Supabase URL")
    return url


def _jwt_audience() -> str:
    return os.environ.get("SUPABASE_JWT_AUDIENCE", "authenticated").strip() or "authenticated"


def _decode_supabase_jwt(token: str) -> dict[str, Any]:
    supabase_url = _supabase_url()
    issuer = f"{supabase_url}/auth/v1"
    audience = _jwt_audience()
    header = jwt.get_unverified_header(token)
    algorithm = header.get("alg")

    if algorithm in SUPPORTED_HMAC_ALGORITHMS:
        secret = os.environ.get("SUPABASE_JWT_SECRET", "").strip()
        if not secret:
            raise AuthConfigError("SUPABASE_JWT_SECRET is required for HS256 Supabase JWTs")
        key: Any = secret
        algorithms = [algorithm]
    elif algorithm in SUPPORTED_ASYMMETRIC_ALGORITHMS:
        jwks_url = f"{issuer}/.well-known/jwks.json"
        key = _jwks_client(jwks_url).get_signing_key_from_jwt(token).key
        algorithms = [algorithm]
    else:
        raise InvalidTokenError("Unsupported JWT signing algorithm")

    claims = jwt.decode(
        token,
        key=key,
        algorithms=algorithms,
        audience=audience,
        issuer=issuer,
        leeway=30,
        options={"require": ["aud", "exp", "iss", "sub"]},
    )
    if not isinstance(claims, dict):
        raise InvalidTokenError("JWT claims must be an object")
    return claims


def _bearer_error(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> CurrentUser:
    """Verify the Supabase access token and return the token subject as owner_id."""
    if not authorization:
        raise _bearer_error()

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _bearer_error("Invalid authorization header")

    try:
        claims = _decode_supabase_jwt(token.strip())
    except AuthConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except (InvalidTokenError, PyJWKClientError) as exc:
        raise _bearer_error("Invalid or expired access token") from exc

    owner_id = claims.get("sub")
    if not isinstance(owner_id, str) or not owner_id:
        raise _bearer_error("Token subject is missing")

    role = claims.get("role")
    if role != "authenticated":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated user token required",
        )

    email = claims.get("email")
    return CurrentUser(
        owner_id=owner_id,
        email=email if isinstance(email, str) else None,
        role=role,
        claims=claims,
    )
