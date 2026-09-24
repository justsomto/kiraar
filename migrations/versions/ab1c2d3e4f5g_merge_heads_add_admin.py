"""Merge migration heads and add admin table

Revision ID: ab1c2d3e4f5g
Revises: 008b378e5c10, 8e7f3a1b2c4d
Create Date: 2026-07-21 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ab1c2d3e4f5g'
down_revision = ('008b378e5c10', '8e7f3a1b2c4d')
branch_labels = None
depends_on = None


def upgrade():
    # Create admin table
    op.create_table('admin',
        sa.Column('admin_id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=225), nullable=False),
        sa.Column('password', sa.String(length=225), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('admin_id'),
        sa.UniqueConstraint('email')
    )


def downgrade():
    op.drop_table('admin')

