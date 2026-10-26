import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ergocare.db")

# For SQLite, add connect_args; safe to remove for Postgres
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def create_db_tables():
    from app.models import assessment, sensors, consent  # noqa: F401 – registers models
    Base.metadata.create_all(bind=engine)
    _migrate()


# Columns added after the first release. create_all() only creates missing tables,
# it never adds columns to existing ones, so an older ergocare.db would otherwise
# fail at runtime with "no such column".
_ADDED_COLUMNS = [
    ("assessment_sessions", "access_token", "VARCHAR"),
    ("assessment_sessions", "client_name",  "VARCHAR"),
    ("assessment_sessions", "client_email", "VARCHAR"),
    ("assessment_sessions", "client_phone", "VARCHAR"),
    ("assessment_sessions", "client_age",   "INTEGER"),
    ("assessment_sessions", "client_job",   "VARCHAR"),
    ("sensor_links", "baseline_started_at", "DATETIME"),
]


def _existing_columns(table: str) -> set:
    from sqlalchemy import inspect
    return {c["name"] for c in inspect(engine).get_columns(table)}


def _migrate() -> None:
    """Idempotently add columns that older databases are missing."""
    from sqlalchemy import text
    for table, column, coltype in _ADDED_COLUMNS:
        try:
            if column in _existing_columns(table):
                continue
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}"))
            print(f"[db] migrated: added {table}.{column}")
        except Exception as exc:  # noqa: BLE001 - never block startup on a migration
            print(f"[db] migration skipped {table}.{column}: {exc}")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
