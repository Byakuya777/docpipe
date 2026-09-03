from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings

# pool_pre_ping keeps long-lived worker processes from handing out connections
# that Postgres has already closed.
engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)

# expire_on_commit=False so ORM objects stay readable after commit() — the task
# reads doc.id/doc.status after committing status transitions.
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    """FastAPI dependency: one session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
