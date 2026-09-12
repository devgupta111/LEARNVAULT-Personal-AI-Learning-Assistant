"""
models/user.py

SQLAlchemy ORM model for the users table.
Persists authenticated user profiles created via Google Sign-In.
"""

from sqlalchemy import Column, String, DateTime
from sqlalchemy.sql import func

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id = Column(String(255), primary_key=True, index=True)
    email = Column(String(255), nullable=True, index=True)
    username = Column(String(255), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
