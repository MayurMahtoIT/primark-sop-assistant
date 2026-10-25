"""Bearer-JWT authentication against the client's IdP (JWKS, RS256)."""

import logging
from dataclasses import dataclass

import jwt
from fastapi import HTTPException, Request, status
from jwt import PyJWKClient

from app.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class User:
    id: str
    country: str | None = None


class Authenticator:
    def __init__(self, settings: Settings):
        self._s = settings
        self._jwks = (
            None
            if settings.auth_disabled
            else PyJWKClient(settings.jwks_url, cache_keys=True, lifespan=3600, timeout=5)
        )

    def authenticate(self, request: Request) -> User:
        if self._s.auth_disabled:
            return User(id="local-dev", country=request.headers.get("x-debug-country"))

        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, "Missing bearer token", {"WWW-Authenticate": "Bearer"}
            )
        try:
            key = self._jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self._s.jwt_audience,
                issuer=self._s.jwt_issuer,
                options={"require": ["exp", "iss", "sub"]},
                leeway=30,
            )
        except jwt.PyJWTError as exc:
            logger.info("jwt_rejected", extra={"ctx": {"error": type(exc).__name__}})
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, "Invalid token", {"WWW-Authenticate": "Bearer"}
            ) from exc

        country = claims.get(self._s.jwt_country_claim)
        return User(id=str(claims["sub"]), country=str(country).upper()[:2] if country else None)


def get_current_user(request: Request) -> User:
    return request.app.state.authenticator.authenticate(request)
