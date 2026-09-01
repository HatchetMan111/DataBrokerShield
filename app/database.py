from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import get_settings

settings = get_settings()

connect_args = {"check_same_thread": False}
if settings.db_is_memory:
    engine = create_engine(settings.db_url, connect_args=connect_args, poolclass=StaticPool)
else:
    settings.db_file.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(settings.db_url, connect_args=connect_args)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
