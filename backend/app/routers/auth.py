from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import (MIN_PASSWORD, authenticate, change_password, current_session, current_user, end_session,
                    start_session, verify_password)
from ..database import get_db
from ..models import AuthSession, ConversionJob, User
from ..schemas import ChangePasswordIn, LoginIn, ProfileOut, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=UserOut)
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)) -> User:
    user = authenticate(db, body.username, body.password)
    if user is None:
        raise HTTPException(401, "Incorrect username or password.")
    start_session(db, response, user, body.remember)
    return user


@router.post("/logout", status_code=204)
def logout(response: Response, bom_session: str | None = Cookie(None, include_in_schema=False),
           db: Session = Depends(get_db)) -> None:
    end_session(db, response, bom_session)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> User:
    return user


@router.get("/profile", response_model=ProfileOut)
def profile(user: User = Depends(current_user), session: AuthSession = Depends(current_session),
            db: Session = Depends(get_db)) -> ProfileOut:
    # jobs record the display name, not the user id
    count = db.execute(select(func.count()).select_from(ConversionJob).where(
        ConversionJob.user_name == user.display_name, ConversionJob.status == "SUCCESS")).scalar_one()
    return ProfileOut(username=user.username, email=user.email, full_name=user.full_name,
                      extraction_count=count, last_login=session.created_at)


@router.post("/change-password", status_code=204)
def update_password(body: ChangePasswordIn, user: User = Depends(current_user),
                    session: AuthSession = Depends(current_session), db: Session = Depends(get_db)) -> None:
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect.")
    if len(body.new_password) < MIN_PASSWORD:
        raise HTTPException(400, f"New password must be at least {MIN_PASSWORD} characters.")
    if body.new_password == body.current_password:
        raise HTTPException(400, "New password must be different from the current password.")
    change_password(db, user, session, body.new_password)
