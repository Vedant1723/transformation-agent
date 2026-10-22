"""Persist dataset exclusions and a fixed evaluation version."""
from alembic import op
import sqlalchemy as sa
revision = 'g206_dataset_policy'
down_revision = 'f205_dataset_versions'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('transformation_dataset_policies',
        sa.Column('user_id', sa.Integer(), primary_key=True),
        sa.Column('state', sa.JSON(), nullable=False))


def downgrade():
    op.drop_table('transformation_dataset_policies')
