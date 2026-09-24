"""Merge heads after admin and payout migrations

Revision ID: d4e5f6a7b8c9
Revises: ab1c2d3e4f5g, b8c7a2f6d9e1
Create Date: 2026-07-22 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd4e5f6a7b8c9'
down_revision = ('ab1c2d3e4f5g', 'b8c7a2f6d9e1')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
