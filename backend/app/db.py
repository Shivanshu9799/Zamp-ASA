from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from . import config


def _normalise_url(url: str) -> str:
    # Render/Heroku hand out postgres:// which SQLAlchemy 2 no longer accepts
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None):
    url = _normalise_url(url or config.DATABASE_URL)
    if url.startswith("sqlite"):
        if ":memory:" not in url:
            path = url.split("///", 1)[-1]
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        eng = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(eng, "connect")
        def _pragma(dbapi_conn, _):  # WAL so the SSE poller can read while a run writes
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()

        return eng
    return create_engine(url, pool_pre_ping=True)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@contextmanager
def session_scope():
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
