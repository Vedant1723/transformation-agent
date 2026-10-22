"""Immutable, user-owned transformation dataset snapshots."""
from alembic import op
import sqlalchemy as sa
revision = 'f205_dataset_versions'
down_revision = 'e104_chat_workspace'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('transformation_datasets',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('manifest', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False))
    op.create_index('ix_transformation_datasets_user_id', 'transformation_datasets', ['user_id'])


def downgrade():
    op.drop_table('transformation_datasets')
