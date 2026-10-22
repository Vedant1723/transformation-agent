"""create control room activity tables

Revision ID: b7c451a2d9ef
Revises: c8c182df853a
Create Date: 2026-09-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7c451a2d9ef"
down_revision: Union[str, Sequence[str], None] = "c8c182df853a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("messages_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])
    op.create_table(
        "activity_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("agent_name", sa.String(length=100), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("summary", sa.String(length=1000), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_activity_events_user_id", "activity_events", ["user_id"])
    op.create_index(
        "ix_activity_events_conversation_id",
        "activity_events",
        ["conversation_id"],
    )
    op.create_index(
        "ix_activity_events_event_type", "activity_events", ["event_type"]
    )
    op.create_index(
        "ix_activity_events_created_at", "activity_events", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_activity_events_created_at", table_name="activity_events")
    op.drop_index("ix_activity_events_event_type", table_name="activity_events")
    op.drop_index(
        "ix_activity_events_conversation_id", table_name="activity_events"
    )
    op.drop_index("ix_activity_events_user_id", table_name="activity_events")
    op.drop_table("activity_events")
    op.drop_index("ix_conversations_user_id", table_name="conversations")
    op.drop_table("conversations")
