from sqlmodel import SQLModel, create_engine, Session
import os

# Use SQLite for local dev, Postgres for AWS Production
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./qmetrum.db")

engine = create_engine(DATABASE_URL, echo=False)

def init_db():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session