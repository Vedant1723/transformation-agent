"""Saved transformation chat checkpoints; no changes to existing workbench tables."""
from alembic import op
import sqlalchemy as sa
revision = 'e104_chat_workspace'
down_revision = 'd92e87000a12'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('transformation_sessions',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('user_id',sa.Integer(),nullable=False),
        sa.Column('title',sa.String(200),nullable=False),
        sa.Column('version',sa.Integer(),nullable=False),
        sa.Column('state',sa.JSON(),nullable=False),
        sa.Column('updated_at',sa.DateTime(),nullable=False))
    op.create_index('ix_transformation_sessions_user_id','transformation_sessions',['user_id'])


def downgrade():
    op.drop_table('transformation_sessions')
