# app/database.py
# This file creates the database connection and session.
#
# Think of it like this:
# - `engine` = the actual connection to PostgreSQL (like a phone line)
# - `SessionLocal` = a temporary workspace for one request (like a phone call)
# - `Base` = the parent class all our database models inherit from
# - `get_db()` = a function that opens a session, gives it to a route,
#                then closes it automatically when the request is done

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.config import settings

# Create the database engine
# pool_pre_ping=True means SQLAlchemy will test the connection
# before using it — prevents errors from stale connections
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    echo=settings.DEBUG  # logs all SQL queries in debug mode
)

# Each instance of SessionLocal is a database session (one per request)
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

# Base class for all our database models (tables)
Base = declarative_base()


# Dependency function used in FastAPI routes
# Usage: def my_route(db: Session = Depends(get_db))
# FastAPI automatically calls this, passes the session,
# and closes it when the request finishes
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()