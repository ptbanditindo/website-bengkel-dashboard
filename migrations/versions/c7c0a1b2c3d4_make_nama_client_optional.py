"""make vehicle nama_client optional

Revision ID: c7c0a1b2c3d4
Revises: fa7fa27bbb86
Create Date: 2026-10-14

Allows a vehicle to be registered from a photo with only a plate number; the
client name can be completed later via the local UI.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c7c0a1b2c3d4'
down_revision: Union[str, None] = 'fa7fa27bbb86'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('vehicles', schema=None) as batch_op:
        batch_op.alter_column(
            'nama_client',
            existing_type=sa.String(length=255),
            nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table('vehicles', schema=None) as batch_op:
        batch_op.alter_column(
            'nama_client',
            existing_type=sa.String(length=255),
            nullable=False,
        )
