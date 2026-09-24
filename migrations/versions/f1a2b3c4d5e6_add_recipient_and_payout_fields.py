"""add recipient_code and payout tracking

Revision ID: f1a2b3c4d5e6
Revises: d4e5f6a7b8c9
Create Date: 2026-07-22 00:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f1a2b3c4d5e6'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade():
    # Add recipient_code to professional
    op.add_column('professional', sa.Column('recipient_code', sa.String(length=100), nullable=True))
    # Add payout tracking to booking
    op.add_column('booking', sa.Column('is_paid_out', sa.Boolean(), nullable=True, server_default=sa.text('0')))
    op.add_column('booking', sa.Column('payout_reference', sa.String(length=255), nullable=True))
    # Remove server_default to keep schema clean
    with op.get_context().autocommit_block():
        op.execute("ALTER TABLE booking ALTER COLUMN is_paid_out DROP DEFAULT")


def downgrade():
    op.drop_column('booking', 'payout_reference')
    op.drop_column('booking', 'is_paid_out')
    op.drop_column('professional', 'recipient_code')
