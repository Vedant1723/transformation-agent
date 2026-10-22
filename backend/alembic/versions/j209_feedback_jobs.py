"""Durable feedback training jobs; no automatic model activation."""
from alembic import op
import sqlalchemy as sa
revision='j209_feedback_jobs'
down_revision='i208_training_bundles'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('transformation_training_jobs',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('user_id',sa.Integer(),nullable=False),
        sa.Column('bundle_id',sa.Integer(),nullable=False),
        sa.Column('request_key',sa.String(100),nullable=False),
        sa.Column('status',sa.String(30),nullable=False),
        sa.Column('running_slot',sa.Integer(),nullable=True,unique=True),
        sa.Column('settings',sa.JSON(),nullable=False),
        sa.Column('result',sa.JSON(),nullable=False),
        sa.UniqueConstraint('user_id','request_key'))
    op.create_index('ix_transformation_training_jobs_user_id','transformation_training_jobs',['user_id'])


def downgrade():
    op.drop_table('transformation_training_jobs')
