from sqlmodel import SQLModel, create_engine, Session
import os

# DATABASE_URL examples:
#   sqlite:///./qmetrum.db                                      (local dev, default)
#   postgresql+psycopg2://user:pass@host:5432/qsight             (RDS / Aurora / any Postgres)
#   postgresql+psycopg2://user:pass@host:5432/qsight?sslmode=require  (RDS prod)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./qmetrum.db")

engine_kwargs: dict = {"echo": False}
if DATABASE_URL.startswith("sqlite"):
    # Needed for background worker threads (forecast jobs) in local SQLite mode.
    engine_kwargs["connect_args"] = {"check_same_thread": False}
elif DATABASE_URL.startswith(("postgresql", "postgres", "cockroachdb")):
    # Sane defaults for managed Postgres (RDS / Aurora). pool_pre_ping
    # avoids stale-connection errors after RDS failovers; pool_recycle
    # rotates connections before any idle-timeout closes them server-side.
    engine_kwargs.update(
        pool_pre_ping=True,
        pool_recycle=1800,    # 30 minutes
        pool_size=5,
        max_overflow=5,
    )

engine = create_engine(DATABASE_URL, **engine_kwargs)


def init_db():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
