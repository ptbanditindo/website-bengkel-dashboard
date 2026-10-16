"""add stock items

Revision ID: a1b2c3d4e5f6
Revises: c7c0a1b2c3d4
Create Date: 2026-10-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'c7c0a1b2c3d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('stock_items',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('nama', sa.String(length=255), nullable=False),
    sa.Column('harga_modal', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('harga_jual', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_stock_items'))
    )


def downgrade() -> None:
    op.drop_table('stock_items')
