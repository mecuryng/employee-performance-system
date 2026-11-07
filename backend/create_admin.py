import getpass

from sqlalchemy import select

from app.database import Base, SessionLocal, engine
from app.routers.auth import User, _password_hash


def main() -> None:
    Base.metadata.create_all(bind=engine)
    email = input("Admin email: ").strip().lower()
    full_name = input("Admin full name: ").strip()
    password = getpass.getpass("Admin password (12+ characters): ")
    if len(password) < 12:
        raise SystemExit("Password must be at least 12 characters")
    with SessionLocal() as db:
        if db.scalar(select(User.id).where(User.email == email)):
            raise SystemExit("That email is already registered")
        db.add(User(email=email, full_name=full_name, password_hash=_password_hash(password), role="admin"))
        db.commit()
    print("Administrator created")


if __name__ == "__main__":
    main()
