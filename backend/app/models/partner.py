from datetime import datetime
from sqlalchemy import Integer, String, JSON, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database.base import Base


class PartnerModel(Base):
    __tablename__ = 'partners'
    __table_args__ = (UniqueConstraint('user_id', 'code', name='uq_partner_user_code'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    routes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    contract: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    assessment: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
