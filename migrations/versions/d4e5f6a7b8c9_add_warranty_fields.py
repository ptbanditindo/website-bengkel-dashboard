"""add warranty completeness + claim date fields

Revision ID: d4e5f6a7b8c9
Revises: b2c3d4e5f6a7
Create Date: 2026-10-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('service_records', schema=None) as batch_op:
        batch_op.add_column(sa.Column('bergaransi', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('tanggal_klaim', sa.Date(), nullable=True))
    op.execute("UPDATE service_records SET bergaransi = 1 WHERE garansi_sampai IS NOT NULL")


def downgrade() -> None:
    with op.batch_alter_table('service_records', schema=None) as batch_op:
        batch_op.drop_column('tanggal_klaim')
        batch_op.drop_column('bergaransi')
