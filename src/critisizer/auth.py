import hashlib
import hmac
import secrets
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from critisizer.deps import SessionDep
from critisizer.models import User

_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    digest = hashlib.scrypt(
        password.encode(), salt=bytes.fromhex(salt_hex), **_SCRYPT
    )
    return hmac.compare_digest(digest.hex(), digest_hex)


# Checked when the email is unknown, so a wrong email and a wrong password
# take about the same time.
DUMMY_HASH = hash_password("not-a-real-password")


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


bearer = HTTPBearer(auto_error=False)


def current_user(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    unauthorized = {"WWW-Authenticate": "Bearer"}
    if credentials is None:
        raise HTTPException(401, "Missing bearer token", headers=unauthorized)
    user = session.scalar(
        select(User).where(User.token_hash == hash_token(credentials.credentials))
    )
    if user is None:
        raise HTTPException(401, "Invalid token", headers=unauthorized)
    return user


CurrentUser = Annotated[User, Depends(current_user)]