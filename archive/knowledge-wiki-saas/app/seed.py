import sys

from sqlalchemy import select

from app.config import BOOTSTRAP_ADMIN_EMAIL, BOOTSTRAP_ADMIN_PASSWORD
from app.db import SessionLocal
from app.models import User
from app.security import hash_password


def main() -> None:
    if not BOOTSTRAP_ADMIN_EMAIL or not BOOTSTRAP_ADMIN_PASSWORD:
        print("Bootstrap admin not configured; skipping.")
        return
    db = SessionLocal()
    try:
        existing = db.scalar(select(User).where(User.email == BOOTSTRAP_ADMIN_EMAIL))
        if existing:
            if not existing.is_platform_admin:
                raise RuntimeError("Bootstrap email exists but is not a platform administrator.")
            print("Bootstrap administrator already exists; skipping.")
            return
        admin = User(
            email=BOOTSTRAP_ADMIN_EMAIL,
            display_name="Platform Admin",
            password_hash=hash_password(BOOTSTRAP_ADMIN_PASSWORD),
            is_platform_admin=True,
        )
        db.add(admin)
        db.commit()
        print("Platform administrator created.")
    except Exception as exc:
        db.rollback()
        print("Bootstrap failed: " + str(exc), file=sys.stderr)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
