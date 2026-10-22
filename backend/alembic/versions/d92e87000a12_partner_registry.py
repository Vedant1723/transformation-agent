"""Add persisted partner registry."""
from alembic import op
import sqlalchemy as sa
revision = 'd92e87000a12'
down_revision = 'b7c451a2d9ef'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('partners',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(80), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('routes', sa.JSON(), nullable=False),
        sa.Column('contract', sa.JSON(), nullable=False),
        sa.Column('assessment', sa.JSON(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('user_id', 'code', name='uq_partner_user_code'))
    op.create_index('ix_partners_user_id', 'partners', ['user_id'])


def downgrade():
    op.drop_table('partners')
