"""Password hashing, sign-in sessions and the `current_user` dependency.

Passwords: scrypt (standard library) with a random salt per user.
Sessions:  a random token in an HttpOnly cookie; the database only keeps its sha256, so a leaked
           database cannot be used to sign in. A cookie (not a header) is used so that the plain
           download links in the history keep working.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Cookie, Depends, HTTPException, Response
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .models import AuthSession, User

COOKIE_NAME = "bom_session"
MIN_PASSWORD = 8

_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P)
    return f"scrypt${_N}${_R}${_P}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, digest = stored.split("$")
        if algo != "scrypt":
            return False
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


# checked against when the user does not exist, so a wrong username takes as long as a wrong password
_DUMMY_HASH = hash_password(secrets.token_hex(16))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def authenticate(db: Session, login: str, password: str) -> User | None:
    login = login.strip().lower()
    user = db.execute(select(User).where(or_(User.username == login, User.email == login))).scalar_one_or_none()
    if user is None:
        verify_password(password, _DUMMY_HASH)
        return None
    if not verify_password(password, user.password_hash) or not user.active:
        return None
    return user


def start_session(db: Session, response: Response, user: User, remember: bool) -> None:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    lifetime = timedelta(days=settings.remember_days) if remember else timedelta(hours=settings.session_hours)
    token = secrets.token_urlsafe(32)
    db.execute(delete(AuthSession).where(AuthSession.expires_at < now))  # housekeeping
    db.add(AuthSession(token_hash=_token_hash(token), user_id=user.id, expires_at=now + lifetime))
    db.commit()
    # without "remember" the cookie has no max_age, so it is dropped when the browser closes
    response.set_cookie(COOKIE_NAME, token, max_age=int(lifetime.total_seconds()) if remember else None,
                        httponly=True, samesite="lax", secure=settings.cookie_secure, path="/")


def end_session(db: Session, response: Response, token: str | None) -> None:
    if token:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == _token_hash(token)))
        db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")


def current_user(
    bom_session: str | None = Cookie(None, include_in_schema=False),
    db: Session = Depends(get_db),
) -> User:
    if bom_session:
        user = db.execute(
            select(User).join(AuthSession, AuthSession.user_id == User.id)
            .where(AuthSession.token_hash == _token_hash(bom_session),
                   AuthSession.expires_at > func.now(), User.active.is_(True))
        ).scalar_one_or_none()
        if user is not None:
            return user
    raise HTTPException(401, "Please sign in.")


def current_session(
    bom_session: str | None = Cookie(None, include_in_schema=False),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> AuthSession:
    """The signed-in session itself (current_user has already checked it is valid)."""
    return db.execute(
        select(AuthSession).where(AuthSession.token_hash == _token_hash(bom_session or ""))
    ).scalar_one()


def change_password(db: Session, user: User, keep: AuthSession, new_password: str) -> None:
    """Set a new password and sign the user out everywhere except the current session."""
    user.password_hash = hash_password(new_password)
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id, AuthSession.id != keep.id))
    db.commit()
