"""Add professional payout fields and complaints table

Revision ID: b8c7a2f6d9e1
Revises: 008b378e5c10
Create Date: 2026-07-22 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'b8c7a2f6d9e1'
down_revision = '008b378e5c10'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table('complaint'):
        op.create_table(
            'complaint',
            sa.Column('complaint_id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('professional_id', sa.Integer(), nullable=False),
            sa.Column('booking_id', sa.Integer(), nullable=False),
            sa.Column('subject', sa.String(length=255), nullable=False),
            sa.Column('message', sa.Text(), nullable=False),
            sa.Column('status', sa.String(length=50), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('complaint_id')
        )

    professional_columns = {col['name'] for col in inspector.get_columns('professional')}
    with op.batch_alter_table('professional', schema=None) as batch_op:
        if 'bank_name' not in professional_columns:
            batch_op.add_column(sa.Column('bank_name', sa.String(length=225), nullable=True))
        if 'account_number' not in professional_columns:
            batch_op.add_column(sa.Column('account_number', sa.String(length=20), nullable=True))
        if 'account_name' not in professional_columns:
            batch_op.add_column(sa.Column('account_name', sa.String(length=225), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table('complaint'):
        op.drop_table('complaint')

    professional_columns = {col['name'] for col in inspector.get_columns('professional')}
    with op.batch_alter_table('professional', schema=None) as batch_op:
        if 'account_name' in professional_columns:
            batch_op.drop_column('account_name')
        if 'account_number' in professional_columns:
            batch_op.drop_column('account_number')
        if 'bank_name' in professional_columns:
            batch_op.drop_column('bank_name')
