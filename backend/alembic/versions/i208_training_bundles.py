"""Persist versioned tokenizer and tokenized training data."""
from alembic import op
import sqlalchemy as sa
revision = 'i208_training_bundles'
down_revision = 'h207_quality_scores'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('transformation_training_bundles',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('dataset_id', sa.Integer(), nullable=False),
        sa.Column('bundle', sa.JSON(), nullable=False))
    op.create_index('ix_transformation_training_bundles_user_id', 'transformation_training_bundles', ['user_id'])


def downgrade():
    op.drop_table('transformation_training_bundles')
