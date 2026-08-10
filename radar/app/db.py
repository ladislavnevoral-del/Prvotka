import os
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/rbd_radar.db")

# Render (a další hostingy) dávají URL ve tvaru postgres://,
# SQLAlchemy 2.x vyžaduje postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args,
                       pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class Base(DeclarativeBase):
    pass

def _sqlite_columns(table_name):
    with engine.connect() as conn:
        rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    return {r[1] for r in rows}

# Jednoduché migrace pro lokální MVP: chybějící sloupce se doplní ALTERem.
_MIGRATIONS = {
    "subjects": {
        "court": "TEXT",
        "file_number": "TEXT",
        "city": "TEXT",
        "street": "TEXT",
        "house_number": "TEXT",
        "zip_code": "TEXT",
        "last_entry_date": "DATETIME",
        "source_dataset": "TEXT",
        "justice_subjekt_id": "TEXT",
        "listiny_checked_at": "DATETIME",
    },
    "documents": {
        "score": "INTEGER",
        "doc_type": "TEXT",
        "meeting_date": "DATETIME",
        "ocr_used": "BOOLEAN",
    },
    "signals": {
        "type": "TEXT",
        "label": "TEXT",
        "priority": "INTEGER",
        "value": "TEXT",
    },
}

def _existing_columns(table_name: str) -> set[str]:
    if DATABASE_URL.startswith("sqlite"):
        return _sqlite_columns(table_name)
    insp = inspect(engine)
    if table_name not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(table_name)}


# Mapování typů pro Postgres (SQLite bere obojí).
_PG_TYPES = {"DATETIME": "TIMESTAMP", "BOOLEAN": "BOOLEAN",
             "INTEGER": "INTEGER", "TEXT": "TEXT"}


def init_db():
    from .models import Subject, Document, Signal  # noqa: F401
    Base.metadata.create_all(bind=engine)

    is_pg = DATABASE_URL.startswith("postgresql")
    with engine.begin() as conn:
        for table, additions in _MIGRATIONS.items():
            cols = _existing_columns(table)
            for name, typ in additions.items():
                if name not in cols:
                    col_type = _PG_TYPES.get(typ, typ) if is_pg else typ
                    conn.execute(text(
                        f"ALTER TABLE {table} ADD COLUMN {name} {col_type}"))

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
