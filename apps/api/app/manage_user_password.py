"""Server-side emergency password reset. Run inside API container; password comes from NEW_PASSWORD env."""
from __future__ import annotations
import argparse
import os
from sqlalchemy import select
from app.core.db import get_session_factory
from app.core.security import hash_password
from app.models.core import User


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    args = parser.parse_args()
    new_password = os.getenv("NEW_PASSWORD", "")
    lowered = new_password.lower()
    if len(new_password) < 12 or any(x in lowered for x in ("password", "changeme", "replace")):
        raise SystemExit("NEW_PASSWORD must be a strong non-placeholder password of at least 12 characters")
    db = get_session_factory()()
    try:
        user = db.scalar(select(User).where(User.username == args.username))
        if not user:
            raise SystemExit("User not found")
        user.password_hash = hash_password(new_password)
        db.commit()
        print(f"Password reset completed for {args.username}. Password was not printed.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
