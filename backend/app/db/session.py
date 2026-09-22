"""Database engine and session management."""

from __future__ import annotations

import os
from typing import Generator, Optional
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models.base import Base

DEFAULT_DB_URL = "sqlite:///plantiq.db"


def get_db_url(db_url: Optional[str] = None) -> str:
    """Resolve database URL from argument or environment."""
    if db_url:
        return db_url
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return env_url
    return DEFAULT_DB_URL


def create_db_engine(db_url: Optional[str] = None) -> Engine:
    """Create SQLAlchemy engine with appropriate dialect arguments."""
    url = get_db_url(db_url)
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(url, connect_args=connect_args)


def get_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create session factory for the engine."""
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    """Initialize database tables from SQLAlchemy metadata."""
    Base.metadata.create_all(bind=engine)
