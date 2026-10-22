from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    Integer,
    JSON,
    String
)

from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class KnowledgeItemModel(Base):

    __tablename__ = "knowledge_items"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True
    )

    knowledge_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True
    )

    key: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        index=True
    )

    value: Mapped[dict] = mapped_column(
        JSON,
        nullable=False
    )

    confidence: Mapped[float] = mapped_column(
        Float,
        nullable=False
    )

    scope: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True
    )

    user_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        index=True
    )

    source: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True
    )

    metadata_json: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )