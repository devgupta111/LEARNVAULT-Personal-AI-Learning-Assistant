"""
db/base.py

Declares the SQLAlchemy declarative base.
All ORM models import Base from here.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
