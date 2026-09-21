"""Lazy SQLAlchemy configuration for the PostgreSQL database."""

import os
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

DATABASE_URL_ENVIRONMENT_VARIABLE = "DATABASE_URL"


def get_database_url() -> str:
    """Return and minimally validate the configured PostgreSQL URL."""
    database_url = os.getenv(DATABASE_URL_ENVIRONMENT_VARIABLE, "").strip()
    if not database_url:
        raise ValueError(
            "DATABASE_URL is not configured. Set it to a PostgreSQL connection URL."
        )

    parsed_url = make_url(database_url)
    if parsed_url.drivername != "postgresql+psycopg":
        raise ValueError(
            "DATABASE_URL must use the postgresql+psycopg SQLAlchemy driver."
        )

    return database_url


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Create and cache the application's synchronous SQLAlchemy engine."""
    return create_engine(get_database_url())


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """Return the session factory future persistence work can use."""
    return sessionmaker(bind=get_engine(), expire_on_commit=False)
