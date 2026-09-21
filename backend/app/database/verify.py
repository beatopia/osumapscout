"""Developer command for verifying PostgreSQL connectivity."""

import sys

from psycopg import OperationalError as PsycopgOperationalError
from sqlalchemy import text
from sqlalchemy.exc import ArgumentError, OperationalError, SQLAlchemyError

from backend.app.database.connection import get_engine


def verify_database_connection() -> None:
    """Connect to PostgreSQL and execute a minimal validation query."""
    with get_engine().connect() as connection:
        result = connection.execute(text("SELECT 1")).scalar_one()

    if result != 1:
        raise RuntimeError("PostgreSQL returned an unexpected verification result.")


def main() -> int:
    """Run database verification with concise, credential-safe errors."""
    try:
        verify_database_connection()
    except ValueError as error:
        print(f"Database configuration error: {error}", file=sys.stderr)
        return 1
    except ArgumentError:
        print(
            "Database configuration error: DATABASE_URL is not a valid SQLAlchemy URL.",
            file=sys.stderr,
        )
        return 1
    except OperationalError as error:
        if isinstance(error.orig, PsycopgOperationalError):
            print(
                "Database connection failed. Check that PostgreSQL is running and "
                "that the configured host, database, username, and password are correct.",
                file=sys.stderr,
            )
        else:
            print("Database connection failed.", file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print(
            "Database verification failed while communicating with PostgreSQL.",
            file=sys.stderr,
        )
        return 1
    except RuntimeError as error:
        print(f"Database verification failed: {error}", file=sys.stderr)
        return 1

    print("PostgreSQL connection verified successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
