from app.core.observability import traced as _log_traced, exception_event as _log_exception
from datetime import datetime, timezone
from sqlalchemy import Integer, String, JSON, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database.base import Base


class TransformationSession(Base):
    __tablename__ = 'transformation_sessions'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(200))
    version: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda:datetime.now(timezone.utc))


class TransformationDataset(Base):
    __tablename__ = 'transformation_datasets'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    manifest: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda:datetime.now(timezone.utc))


class TransformationDatasetPolicy(Base):
    __tablename__ = 'transformation_dataset_policies'
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    state: Mapped[dict] = mapped_column(JSON, default=dict)


class TransformationScore(Base):
    __tablename__ = 'transformation_scores'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    dataset_id: Mapped[int] = mapped_column(Integer)
    report: Mapped[dict] = mapped_column(JSON)


class TransformationTrainingBundle(Base):
    __tablename__ = 'transformation_training_bundles'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    dataset_id: Mapped[int] = mapped_column(Integer)
    bundle: Mapped[dict] = mapped_column(JSON)


class TransformationTrainingJob(Base):
    __tablename__ = 'transformation_training_jobs'
    __table_args__ = (UniqueConstraint('user_id','request_key'),)
    id: Mapped[int] = mapped_column(Integer,primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer,index=True)
    bundle_id: Mapped[int] = mapped_column(Integer)
    request_key: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30),default='queued')
    running_slot: Mapped[int | None] = mapped_column(Integer,nullable=True,unique=True)
    settings: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON,default=dict)
