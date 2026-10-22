"""Persist transformation evaluation evidence."""
from alembic import op
import sqlalchemy as sa
revision = 'h207_quality_scores'
down_revision = 'g206_dataset_policy'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('transformation_scores',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('dataset_id', sa.Integer(), nullable=False),
        sa.Column('report', sa.JSON(), nullable=False))
    op.create_index('ix_transformation_scores_user_id', 'transformation_scores', ['user_id'])


def downgrade():
    op.drop_table('transformation_scores')
