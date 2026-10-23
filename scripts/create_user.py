import argparse
import asyncio
import getpass
import sys

from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.security import hash_password
from app.db import repository
from app.db.session import create_engine, create_session_factory

MIN_PASSWORD_LENGTH = 8


async def _create(email: str, password: str) -> bool:
    engine = create_engine(get_settings().database_url)
    try:
        async with create_session_factory(engine)() as db:
            await repository.create_user(db, email, hash_password(password))
        return True
    except IntegrityError:
        return False
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a user account.")
    parser.add_argument("--email", required=True)
    args = parser.parse_args()

    password = getpass.getpass("Password: ")
    if getpass.getpass("Repeat password: ") != password:
        print("The passwords do not match.")
        return 1
    if len(password) < MIN_PASSWORD_LENGTH:
        print(f"The password must have at least {MIN_PASSWORD_LENGTH} characters.")
        return 1

    if asyncio.run(_create(args.email, password)):
        print(f"Created user {repository.normalize_email(args.email)}")
        return 0
    print("A user with that email already exists.")
    return 1


if __name__ == "__main__":
    sys.exit(main())