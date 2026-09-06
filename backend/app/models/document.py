"""
models/document.py

SQLAlchemy ORM model for the documents table.

Status lifecycle:
    PROCESSING  →  READY   (extraction succeeded)
    PROCESSING  →  FAILED  (extraction failed or file is fully scanned)
"""

import uuid
from sqlalchemy import Column, String, Integer, Text, DateTime
from sqlalchemy.sql import func

from app.db.base import Base


class Document(Base):
    __tablename__ = "documents"

    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    # DEV PLACEHOLDER: user_id is hardcoded to "dev-user" during development.
    # Authentication will be added in a later phase.
    # Once JWT auth is implemented, user_id will be derived from the authenticated token.
    user_id = Column(String(36), nullable=False, default="dev-user")

    filename = Column(String(255), nullable=False)
    subject = Column(String(255), nullable=True)
    file_path = Column(String(500), nullable=False)

    status = Column(String(20), nullable=False, default="PROCESSING")

    page_count = Column(Integer, nullable=True)

    error_message = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
