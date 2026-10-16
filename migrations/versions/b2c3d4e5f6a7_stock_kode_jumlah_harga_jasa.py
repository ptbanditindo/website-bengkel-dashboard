"""stock kode + jumlah, harga_jasa, part stock link

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-10-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('stock_items', sa.Column('kode', sa.String(length=64), nullable=True))
    op.create_index('uq_stock_items_kode', 'stock_items', ['kode'], unique=True)
    op.add_column('stock_items', sa.Column('jumlah', sa.Integer(), nullable=False, server_default='0'))

    op.create_table('harga_jasa',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('nama', sa.String(length=255), nullable=False),
    sa.Column('keuntungan', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_harga_jasa'))
    )

    op.add_column('service_parts', sa.Column('stock_item_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('service_parts', 'stock_item_id')
    op.drop_table('harga_jasa')
    op.drop_column('stock_items', 'jumlah')
    op.drop_index('uq_stock_items_kode', 'stock_items')
    op.drop_column('stock_items', 'kode')
