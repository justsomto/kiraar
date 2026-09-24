"""add price_updated fields

Revision ID: 8e7f3a1b2c4d
Revises: 0fa30146655d
Create Date: 2026-07-20 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8e7f3a1b2c4d'
down_revision = '0fa30146655d'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('booking', sa.Column('price_updated', sa.Boolean(), nullable=True, server_default='0'))
    op.add_column('booking', sa.Column('price_updated_by', sa.String(length=50), nullable=True))


def downgrade():
    op.drop_column('booking', 'price_updated_by')
    op.drop_column('booking', 'price_updated')
