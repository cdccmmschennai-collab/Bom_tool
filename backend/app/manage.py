"""User administration from the command line (there is no admin screen).

    python -m app.manage create-user USERNAME [--email E] [--name "Full Name"]
    python -m app.manage set-password USERNAME
    python -m app.manage disable-user USERNAME      # also signs the user out everywhere
    python -m app.manage enable-user USERNAME
    python -m app.manage list-users

With Docker:  docker compose exec backend python -m app.manage create-user USERNAME
The password is asked for interactively; pipe it in with --password-stdin for scripts.
"""
from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import delete, or_, select

from .auth import MIN_PASSWORD, hash_password
from .database import Base, SessionLocal, engine
from .models import AuthSession, User

def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
    else:
        password = getpass.getpass("Password: ")
        if getpass.getpass("Repeat password: ") != password:
            sys.exit("Passwords do not match.")
    if len(password) < MIN_PASSWORD:
        sys.exit(f"Password must be at least {MIN_PASSWORD} characters.")
    return password


def _get(db, username: str) -> User:
    user = db.execute(select(User).where(User.username == username.strip().lower())).scalar_one_or_none()
    if user is None:
        sys.exit(f"No user {username!r}.")
    return user


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.manage", description="Manage BOM Tool users.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("create-user")
    p.add_argument("username")
    p.add_argument("--email")
    p.add_argument("--name", help="full name, shown in the history")
    p.add_argument("--password-stdin", action="store_true")
    p = sub.add_parser("set-password")
    p.add_argument("username")
    p.add_argument("--password-stdin", action="store_true")
    for cmd in ("disable-user", "enable-user"):
        sub.add_parser(cmd).add_argument("username")
    sub.add_parser("list-users")
    args = parser.parse_args(argv)

    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if args.cmd == "create-user":
            username = args.username.strip().lower()
            email = args.email.strip().lower() if args.email else None
            taken = [User.username == username] + ([User.email == email] if email else [])
            if db.execute(select(User).where(or_(*taken))).first():
                sys.exit("A user with this username or e-mail already exists.")
            db.add(User(username=username, email=email, full_name=args.name,
                        password_hash=hash_password(_read_password(args.password_stdin))))
            db.commit()
            print(f"Created user {username}.")
        elif args.cmd == "set-password":
            user = _get(db, args.username)
            user.password_hash = hash_password(_read_password(args.password_stdin))
            db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
            db.commit()
            print(f"Password changed for {user.username} (existing sessions signed out).")
        elif args.cmd in ("disable-user", "enable-user"):
            user = _get(db, args.username)
            user.active = args.cmd == "enable-user"
            if not user.active:
                db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
            db.commit()
            print(f"{user.username}: {'enabled' if user.active else 'disabled'}.")
        else:
            for u in db.execute(select(User).order_by(User.username)).scalars():
                print(f"{u.username:<20} {u.email or '':<30} {u.full_name or '':<25} {'active' if u.active else 'disabled'}")


if __name__ == "__main__":
    main()
