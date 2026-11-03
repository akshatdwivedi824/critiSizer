from fastapi import APIRouter, HTTPException
from psycopg.errors import UniqueViolation
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from critisizer.auth import (
    DUMMY_HASH,
    hash_password,
    hash_token,
    new_token,
    verify_password,
)
from critisizer.deps import SessionDep
from critisizer.models import User

router = APIRouter(prefix="/api", tags=["accounts"])

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class Credentials(BaseModel):
    email: str = Field(max_length=255, pattern=EMAIL_PATTERN)
    password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    id: int
    email: str


class TokenOut(BaseModel):
    token: str
    token_type: str = "bearer"


@router.post("/signup", response_model=UserOut, status_code=201)
def signup(body: Credentials, session: SessionDep) -> UserOut:
    user = User(email=body.email.lower(), password_hash=hash_password(body.password))
    try:
        with session.begin_nested():
            session.add(user)
    except IntegrityError as exc:
        if isinstance(exc.orig, UniqueViolation):
            raise HTTPException(409, "Email already registered") from exc
        raise
    session.commit()
    return UserOut(id=user.id, email=user.email)


@router.post("/login", response_model=TokenOut)
def login(body: Credentials, session: SessionDep) -> TokenOut:
    user = session.scalar(select(User).where(User.email == body.email.lower()))
    stored = user.password_hash if user else DUMMY_HASH
    password_ok = verify_password(body.password, stored)
    if user is None or not password_ok:
        raise HTTPException(401, "Wrong email or password")
    token = new_token()
    user.token_hash = hash_token(token)
    session.commit()
    return TokenOut(token=token)