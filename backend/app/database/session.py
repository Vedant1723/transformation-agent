"""Database lifecycle. Credentials must come from deployment configuration."""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv('DATABASE_URL', '').strip()
if not DATABASE_URL:
    raise RuntimeError('DATABASE_URL must be configured before starting the service.')

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    from app.core.observability import event, exception_event
    event('database.session_opened', level=10)
    try:
        with SessionLocal() as db:
            yield db
    except Exception as exc:
        exception_event('database.request_session', exc)
        raise
    finally:
        event('database.session_closed', level=10)
